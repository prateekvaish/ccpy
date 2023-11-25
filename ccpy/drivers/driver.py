"""Main calculation driver module of CCpy."""
import numpy as np
from importlib import import_module
from copy import deepcopy
import time
import ccpy.cc
import ccpy.hbar
import ccpy.left
import ccpy.eom_guess
import ccpy.eomcc
from ccpy.drivers.solvers import (
                cc_jacobi,
                left_cc_jacobi,
                eomcc_davidson,
                eomcc_block_davidson,
                eomcc_nonlinear_diis,
                eccc_jacobi,
)
from ccpy.energy.cc_energy import get_LR, get_r0, get_rel, get_rel_ea, get_rel_ip
from ccpy.models.integrals import Integral
from ccpy.models.operators import ClusterOperator, SpinFlipOperator, FockOperator
from ccpy.utilities.printing import (
                get_timestamp,
                cc_calculation_summary,
                eomcc_calculation_summary, leftcc_calculation_summary, print_ee_amplitudes,
                print_sf_amplitudes, sfeomcc_calculation_summary,
                print_ea_amplitudes, eaeomcc_calculation_summary,
                print_ip_amplitudes, ipeomcc_calculation_summary,
                print_dea_amplitudes, deaeomcc_calculation_summary,
)
from ccpy.utilities.utilities import convert_excitations_c_to_f, reorder_triples_amplitudes
from ccpy.interfaces.pyscf_tools import load_pyscf_integrals
from ccpy.interfaces.gamess_tools import load_gamess_integrals


class Driver:

    @classmethod
    def from_pyscf(cls, meanfield, nfrozen, ndelete=0, normal_ordered=True, dump_integrals=False, sorted=True, use_cholesky=False, cholesky_tol=1.0e-09):
        return cls(
                    *load_pyscf_integrals(meanfield, nfrozen, ndelete, normal_ordered=normal_ordered, dump_integrals=dump_integrals, sorted=sorted,
                                          use_cholesky=use_cholesky, cholesky_tol=cholesky_tol)
                  )

    @classmethod
    def from_gamess(cls, logfile, nfrozen, ndelete=0, fcidump=None, onebody=None, twobody=None, normal_ordered=True, sorted=True, data_type=np.float64):
        return cls(
                    *load_gamess_integrals(logfile, fcidump, onebody, twobody, nfrozen, ndelete, normal_ordered=normal_ordered, sorted=sorted, data_type=data_type)
                   )

    def __init__(self, system, hamiltonian, max_number_states=50):
        self.system = system
        self.hamiltonian = hamiltonian
        self.flag_hbar = False
        self.options = {"method": None,
                        "maximum_iterations": 80,
                        "amp_convergence": 1.0e-07,
                        "energy_convergence": 1.0e-07,
                        "energy_shift": 0.0,
                        "diis_size": 6,
                        "RHF_symmetry": (self.system.noccupied_alpha == self.system.noccupied_beta),
                        "diis_out_of_core": False,
                        "davidson_out_of_core": False,
                        "amp_print_threshold": 0.025,
                        "davidson_max_subspace_size": 30,
                        "davidson_solver": "standard",
                        "davidson_selection_method": "overlap"}

        # Disable DIIS for small problems to avoid inherent singularity
        if self.system.noccupied_alpha * self.system.nunoccupied_beta <= 4:
            self.options["diis_size"] = -1

        self.operator_params = {"order": 0,
                                "number_particles": 0,
                                "number_holes": 0,
                                "active_orders": [None],
                                "number_active_indices": None,
                                "pspace_orders": [None]}
        self.T = None
        self.L = [None] * max_number_states
        self.R = [None] * max_number_states
        self.rdm1 = [[None] * max_number_states] * max_number_states
        self.correlation_energy = 0.0
        self.vertical_excitation_energy = np.zeros(max_number_states)
        self.r0 = np.zeros(max_number_states)
        self.relative_excitation_level = np.zeros(max_number_states)
        self.guess_energy = None
        self.guess_vectors = None
        self.guess_order = 0
        self.deltap3 = [None] * max_number_states
        self.ddeltap3 = [None] * max_number_states
        self.deltap4 = [None] * max_number_states
        self.ddeltap4 = [None] * max_number_states

        # Store alpha and beta fock matrices for later usage before HBar overwrites bare Hamiltonian
        self.fock = Integral.from_empty(system, 1, data_type=self.hamiltonian.a.oo.dtype)
        self.fock.a.oo = self.hamiltonian.a.oo.copy()
        self.fock.b.oo = self.hamiltonian.b.oo.copy()
        self.fock.a.vv = self.hamiltonian.a.vv.copy()
        self.fock.b.vv = self.hamiltonian.b.vv.copy()

        # Potentially used container for the CCS-transformed intermediates used in CC3 models. This is required
        # because the CCSDT-like HBar used for R1 and R2 updates in CC3 overwrites the parts of Hbar needed to compute
        # the intermediates used in R3 equation.
        self.cc3_intermediates = None

    def set_operator_params(self, method):
        if method.lower() in ["ccs"]:
            self.operator_params["order"] = 1
            self.operator_params["number_particles"] = 1
            self.operator_params["number_holes"] = 1
        elif method.lower() in ["cc2", "ccd", "ccsd", "eomcc2", "eomccsd", "left_ccsd", "eccc2", "cc3", "eomcc3"]:
            self.operator_params["order"] = 2
            self.operator_params["number_particles"] = 2
            self.operator_params["number_holes"] = 2
        elif method.lower() in ["ccsdt", "eomccsdt", "left_ccsdt"]:
            self.operator_params["order"] = 3
            self.operator_params["number_particles"] = 3
            self.operator_params["number_holes"] = 3
        elif method.lower() in ["ccsdtq"]:
            self.operator_params["order"] = 4
            self.operator_params["number_particles"] = 4
            self.operator_params["number_holes"] = 4
        elif method.lower() in ["ccsdt1", "eomccsdt1"]:
            self.operator_params["order"] = 3
            self.operator_params["number_particles"] = 3
            self.operator_params["number_holes"] = 3
            self.operator_params["active_orders"] = [3]
            self.operator_params["number_active_indices"] = [1]
        elif method.lower() in ["ccsdt_p", "eomccsdt_p", "left_ccsdt_p"]:
            self.operator_params["order"] = 3
            self.operator_params["number_particles"] = 3
            self.operator_params["number_holes"] = 3
            self.operator_params["pspace_orders"] = [3]
        elif method.lower() in ["ipeom2", "left_ipeom2"]:
            self.order = 2
            self.num_particles = 1
            self.num_holes = 2
        elif method.lower() in ["ipeom3", "left_ipeom3"]:
            self.order = 3
            self.num_particles = 2
            self.num_holes = 3
        elif method.lower() in ["eaeom2", "left_eaeom2"]:
            self.order = 2
            self.num_particles = 2
            self.num_holes = 1
        elif method.lower() in ["eaeom3", "left_eaeom3"]:
            self.order = 3
            self.num_particles = 3
            self.num_holes = 2
        elif method.lower() in ["dipeom3", "left_dipeom3"]:
            self.order = 3
            self.num_particles = 1
            self.num_holes = 3
        elif method.lower() in ["dipeom4", "left_dipeom4"]:
            self.order = 4
            self.num_particles = 2
            self.num_holes = 4
        elif method.lower() in ["deaeom2", "left_deaeom2"]:
            self.order = 2
            self.num_particles = 2
            self.num_holes = 0
        elif method.lower() in ["deaeom3", "left_deaeom3"]:
            self.order = 3
            self.num_particles = 3
            self.num_holes = 1
        elif method.lower() in ["deaeom4", "left_deaeom4"]:
            self.order = 4
            self.num_particles = 4
            self.num_holes = 2
        elif method.lower() in ["sfeomccsd"]:
            self.order = 1
            self.Ms = -1
            
    def print_options(self):
        print("   ------------------------------------------")
        for option_key, option_value in self.options.items():
            print("  ", option_key, "=", option_value)
        print("   ------------------------------------------\n")

    def run_mbpt(self, method):

        if method.lower() == "mp2":
            from ccpy.mbpt.mbpt import calc_mp2
            self.correlation_energy = calc_mp2(self.system, self.hamiltonian)
        elif method.lower() == "mp3":
            from ccpy.mbpt.mbpt import calc_mp3
            self.correlation_energy = calc_mp3(self.system, self.hamiltonian)
        elif method.lower() == "mp4":
            from ccpy.mbpt.mbpt import calc_mp4
            self.correlation_energy = calc_mp4(self.system, self.hamiltonian)
        else:
            raise NotImplementedError("MBPT method {} not implemented".format(method.lower()))

    def run_cc(self, method):
        # check if requested CC calculation is implemented in modules
        if method.lower() not in ccpy.cc.MODULES:
            raise NotImplementedError(
                "{} not implemented".format(method.lower())
            )
        # Set operator parameters needed to build T
        self.set_operator_params(method)
        self.options["method"] = method.upper()

        # import the specific CC method module and get its update function
        cc_mod = import_module("ccpy.cc." + method.lower())
        update_function = getattr(cc_mod, 'update')

        # Print the options as a header
        self.print_options()
        print("   CC calculation started on", get_timestamp())

        # Create either the standard CC cluster operator
        if self.T is None:
            self.T = ClusterOperator(self.system,
                                     order=self.operator_params["order"],
                                     active_orders=self.operator_params["active_orders"],
                                     num_active=self.operator_params["number_active_indices"])
        # regardless of restart status, initialize residual anew
        dT = ClusterOperator(self.system,
                             order=self.operator_params["order"],
                             active_orders=self.operator_params["active_orders"],
                             num_active=self.operator_params["number_active_indices"])
        # Run the CC calculation
        self.T, self.correlation_energy, _ = cc_jacobi(update_function,
                                                self.T,
                                                dT,
                                                self.hamiltonian,
                                                self.system,
                                                self.options,
                                               )
        cc_calculation_summary(self.T, self.system.reference_energy, self.correlation_energy, self.system, self.options["amp_print_threshold"])
        print("   CC calculation ended on", get_timestamp())

    def run_ccp(self, method, t3_excitations):
        # check if requested CC calculation is implemented in modules
        if method.lower() not in ccpy.cc.MODULES:
            raise NotImplementedError(
                "{} not implemented".format(method.lower())
            )
        # Set operator parameters needed to build T
        self.set_operator_params(method)
        self.options["method"] = method.upper()

        # import the specific CC method module and get its update function
        cc_mod = import_module("ccpy.cc." + method.lower())
        update_function = getattr(cc_mod, 'update')

        # Convert excitations array to Fortran continuous
        t3_excitations = convert_excitations_c_to_f(t3_excitations)

        # Print the options as a header
        self.print_options()
        print("   CC(P) calculation started on", get_timestamp())

        # Create the CC(P) cluster operator
        n3aaa = t3_excitations["aaa"].shape[0]
        n3aab = t3_excitations["aab"].shape[0]
        n3abb = t3_excitations["abb"].shape[0]
        n3bbb = t3_excitations["bbb"].shape[0]
        excitation_count = [[n3aaa, n3aab, n3abb, n3bbb]]

        # If RHF, copy aab into abb and aaa in bbb
        if self.options["RHF_symmetry"]:
            assert (n3aaa == n3bbb)
            assert (n3aab == n3abb)
            t3_excitations["bbb"] = t3_excitations["aaa"].copy()
            t3_excitations["abb"] = t3_excitations["aab"][:, [2, 0, 1, 5, 3, 4]]  # want abb excitations as a b~<c~ i j~<k~; MUST be this order!

        if self.T is None:
            self.T = ClusterOperator(self.system,
                                     order=self.operator_params["order"],
                                     p_orders=self.operator_params["pspace_orders"],
                                     pspace_sizes=excitation_count)
        else:
            T_new = ClusterOperator(self.system,
                                     order=self.operator_params["order"],
                                     p_orders=self.operator_params["pspace_orders"],
                                     pspace_sizes=excitation_count)
            T_new.unflatten(self.T.flatten(), order=2)
            self.T = T_new

        # regardless of restart status, initialize residual anew
        dT = ClusterOperator(self.system,
                             order=self.operator_params["order"],
                             p_orders=self.operator_params["pspace_orders"],
                             pspace_sizes=excitation_count)
        # Run the CC(P) calculation
        # NOTE: It may not look like it, but t3_excitations is permuted and matches T at this point. It changes from its value at input!
        self.T, self.correlation_energy, _ = cc_jacobi(update_function,
                                                       self.T,
                                                       dT,
                                                       self.hamiltonian,
                                                       self.system,
                                                       self.options,
                                                       t3_excitations)
        cc_calculation_summary(self.T, self.system.reference_energy, self.correlation_energy, self.system, self.options["amp_print_threshold"])
        print("   CC(P) calculation ended on", get_timestamp())

    def run_hbar(self, method, t3_excitations=None):
        # check if requested CC calculation is implemented in modules
        if "hbar_" + method.lower() not in ccpy.hbar.MODULES:
            raise NotImplementedError(
                "HBar for {} not implemented".format(method.lower())
            )

        # import the specific CC method module and get its update function
        hbar_mod = import_module("ccpy.hbar." + "hbar_" + method.lower())
        hbar_build_function = getattr(hbar_mod, 'build_hbar_' + method.lower())

        # Replace the driver hamiltonian with the Hbar
        print("")
        print("   HBar construction began on", get_timestamp(), end="")
        if method.lower() == "cc3":
            self.hamiltonian, self.cc3_intermediates = hbar_build_function(self.T, self.hamiltonian, self.options["RHF_symmetry"], self.system)
        else:
            self.hamiltonian = hbar_build_function(self.T, self.hamiltonian, self.options["RHF_symmetry"], self.system, t3_excitations)
        print("... completed on", get_timestamp(), "\n")
        # Set flag indicating that hamiltonian is set to Hbar is now true
        self.flag_hbar = True

    def run_guess(self, method, multiplicity, roots_per_irrep, nact_occupied=-1, nact_unoccupied=-1, use_symmetry=True, debug=False):
        """Performs the initial guess for a subsequent EOMCC calculation."""
        # check if requested EOM guess calculation is implemented in modules
        if method.lower() not in ccpy.eom_guess.MODULES:
            raise NotImplementedError(
                "{} guess not implemented".format(method.lower())
            )
        # import the specific guess function
        guess_module = import_module("ccpy.eom_guess." + method.lower())
        guess_function = getattr(guess_module, "run_diagonalization")
        # Set operator parameters needed to build the guess R vector
        if method.lower() in ["cis", "sfcis", "eacis", "ipcis"]:
            self.guess_order = 1
        elif method.lower() in ["cisd", "sfcisd", "deacis", "dipcis", "eacisd", "ipcisd"]:
            self.guess_order = 2
        # This is important. Turn off RHF symmetry (even for closed-shell references) when targetting non-singlets
        if multiplicity != 1:
            self.options["RHF_symmetry"] = False
        # Run the initial guess function and save all eigenpairs
        self.guess_energy, self.guess_vectors = guess_function(self.system, self.hamiltonian, multiplicity, roots_per_irrep, nact_occupied, nact_unoccupied, debug=debug, use_symmetry=use_symmetry)

    def run_eomccp(self, method, state_index, t3_excitations, r3_excitations):
        """Performs the EOMCC calculation specified by the user in the input."""
        # check if requested CC calculation is implemented in modules
        if method.lower() not in ccpy.eomcc.MODULES:
            raise NotImplementedError(
                "{} not implemented".format(method.lower())
            )
        # Set operator parameters needed to build R
        self.set_operator_params(method)
        self.options["method"] = method.upper()

        # Ensure that Hbar is set upon entry
        assert (self.flag_hbar)

        # import the specific EOMCC(P) method module and get its update function
        eom_module = import_module("ccpy.eomcc." + method.lower())
        HR_function = getattr(eom_module, 'HR')
        update_function = getattr(eom_module, 'update')

        # Convert excitations array to Fortran continuous
        t3_excitations = convert_excitations_c_to_f(t3_excitations)
        r3_excitations = convert_excitations_c_to_f(r3_excitations)

        # Get dimensions of R3 spincases in P space
        n3aaa_r = r3_excitations["aaa"].shape[0]
        n3aab_r = r3_excitations["aab"].shape[0]
        n3abb_r = r3_excitations["abb"].shape[0]
        n3bbb_r = r3_excitations["bbb"].shape[0]
        excitation_count = [[n3aaa_r, n3aab_r, n3abb_r, n3bbb_r]]

        # If RHF, copy aab into abb and aaa in bbb
        if self.options["RHF_symmetry"]:
            assert (n3aaa_r == n3bbb_r)
            assert (n3aab_r == n3abb_r)
            r3_excitations["bbb"] = r3_excitations["aaa"].copy()
            r3_excitations["abb"] = r3_excitations["aab"][:, [2, 0, 1, 5, 3, 4]]  # want abb excitations as a b~<c~ i j~<k~; MUST be this order!

        if self.R[state_index] is None:
            self.R[state_index] = ClusterOperator(self.system,
                                                  order=self.operator_params["order"],
                                                  p_orders=self.operator_params["pspace_orders"],
                                                  pspace_sizes=excitation_count)
            # regardless of restart status, initialize residual anew
            dR = ClusterOperator(self.system,
                                 order=self.operator_params["order"],
                                 p_orders=self.operator_params["pspace_orders"],
                                 pspace_sizes=excitation_count)
            self.R[state_index].unflatten(self.guess_vectors[:, state_index - 1], order=self.guess_order)
            self.vertical_excitation_energy[state_index] = self.guess_energy[state_index - 1]

        # Form the initial subspace vector
        # B0, _ = np.linalg.qr(self.R[state_index].flatten()[:, np.newaxis])

        # Print the options as a header
        self.print_options()
        print("   EOMCC(P) calculation for root %d started on" % state_index, get_timestamp())
        print("\n   Energy of initial guess = {:>10.10f}".format(self.vertical_excitation_energy[state_index]))
        print_ee_amplitudes(self.R[state_index], self.system, self.R[state_index].order, self.options["amp_print_threshold"])
        self.R[state_index], self.vertical_excitation_energy[state_index], is_converged = eomcc_davidson(HR_function,
                                                                                                         update_function,
                                                                                                         #B0[:, 0],
                                                                                                         self.R[state_index].flatten() / np.linalg.norm(self.R[state_index].flatten()),
                                                                                                         self.R[state_index],
                                                                                                         dR,
                                                                                                         self.vertical_excitation_energy[state_index],
                                                                                                         self.T,
                                                                                                         self.hamiltonian,
                                                                                                         self.system,
                                                                                                         self.options,
                                                                                                         t3_excitations,
                                                                                                         r3_excitations)
        # Compute r0 a posteriori
        self.r0[state_index] = get_r0(self.R[state_index], self.hamiltonian, self.vertical_excitation_energy[state_index])
        # compute the relative excitation level (REL) metric
        self.relative_excitation_level[state_index] = get_rel(self.R[state_index], self.r0[state_index])
        eomcc_calculation_summary(self.R[state_index], self.vertical_excitation_energy[state_index], self.correlation_energy, self.r0[state_index], self.relative_excitation_level[state_index], is_converged, state_index, self.system, self.options["amp_print_threshold"])
        print("   EOMCC(P) calculation for root %d ended on" % state_index, get_timestamp(), "\n")

    def run_eomcc(self, method, state_index):
        """Performs the EOMCC calculation specified by the user in the input."""
        # check if requested CC calculation is implemented in modules
        if method.lower() not in ccpy.eomcc.MODULES:
            raise NotImplementedError(
                "{} not implemented".format(method.lower())
            )
        # Set operator parameters needed to build R
        self.set_operator_params(method)
        self.options["method"] = method.upper()
        # If running EOM-CC3, use the nonlinear excited state DIIS solver
        if method.lower() == "eomcc3":
            self.options["davidson_solver"] = "diis"

        # Ensure that Hbar is set upon entry
        assert(self.flag_hbar)

        # import the specific EOMCC method module and get its update function
        eom_module = import_module("ccpy.eomcc." + method.lower())
        HR_function = getattr(eom_module, 'HR')
        update_function = getattr(eom_module, 'update')

        for i in state_index:
            if self.R[i] is None:
                self.R[i] = ClusterOperator(self.system,
                                            order=self.operator_params["order"],
                                            active_orders=self.operator_params["active_orders"],
                                            num_active=self.operator_params["number_active_indices"])
                self.R[i].unflatten(self.guess_vectors[:, i - 1], order=self.guess_order)
                self.vertical_excitation_energy[i] = self.guess_energy[i - 1]

        # Print the options as a header
        self.print_options()

        # Create the residual R that is re-used for each root
        dR = ClusterOperator(self.system,
                             order=self.operator_params["order"],
                             active_orders=self.operator_params["active_orders"],
                             num_active=self.operator_params["number_active_indices"])

        if self.options["davidson_solver"] == "multiroot":
            print("   Multiroot EOMCC calculation started on", get_timestamp(), "\n")
            # Form the initial subspace vectors
            B0, _ = np.linalg.qr(np.asarray([self.R[i].flatten() for i in state_index]).T)
            print("   Energy of initial guess")
            for istate in state_index:
                print("      Root  {} = {:>10.10f}".format(istate, self.vertical_excitation_energy[istate]))
            self.R, self.vertical_excitation_energy, is_converged = eomcc_block_davidson(HR_function, update_function,
                                                                                         B0,
                                                                                         self.R, dR,
                                                                                         self.vertical_excitation_energy,
                                                                                         self.T, self.hamiltonian,
                                                                                         self.system, state_index, self.options)
            for j, istate in enumerate(state_index):
                # Compute r0 a posteriori
                self.r0[istate] = get_r0(self.R[istate], self.hamiltonian, self.vertical_excitation_energy[istate])
                # compute the relative excitation level (REL) metric
                self.relative_excitation_level[istate] = get_rel(self.R[istate], self.r0[istate])
                eomcc_calculation_summary(self.R[istate], self.vertical_excitation_energy[istate], self.correlation_energy,
                                          self.r0[istate], self.relative_excitation_level[istate], is_converged[j], istate, self.system,
                                          self.options["amp_print_threshold"])
            print("   Multiroot EOMCC calculation ended on", get_timestamp(), "\n")

        elif self.options["davidson_solver"] == "diis": # used for EOM-CC3 calculations ONLY!
            assert method.lower() == "eomcc3"
            for j, istate in enumerate(state_index):
                print("   EOMCC calculation for root %d started on" % istate, get_timestamp())
                print("\n   Energy of initial guess = {:>10.10f}".format(self.vertical_excitation_energy[istate]))
                print_ee_amplitudes(self.R[istate], self.system, self.R[istate].order, self.options["amp_print_threshold"])
                # self.R[istate], self.vertical_excitation_energy[istate], is_converged = eomcc_nonlinear_diis(HR_function, update_function, B0[:, j],
                #                                                                                              self.R[istate], dR, self.vertical_excitation_energy[istate],
                #                                                                                              self.T, self.hamiltonian, self.cc3_intermediates, self.fock,
                #                                                                                              self.system, self.options)
                self.R[istate], self.vertical_excitation_energy[istate], is_converged = eomcc_nonlinear_diis(HR_function, update_function,
                                                                                                             self.R[istate].flatten() / np.linalg.norm(self.R[istate].flatten()),
                                                                                                             self.R[istate], dR, self.vertical_excitation_energy[istate],
                                                                                                             self.T, self.hamiltonian, self.cc3_intermediates, self.fock,
                                                                                                             self.system, self.options)
                # Compute r0 a posteriori
                self.r0[istate] = get_r0(self.R[istate], self.hamiltonian, self.vertical_excitation_energy[istate])
                # compute the relative excitation level (REL) metric
                self.relative_excitation_level[istate] = get_rel(self.R[istate], self.r0[istate])
                eomcc_calculation_summary(self.R[istate], self.vertical_excitation_energy[istate], self.correlation_energy, self.r0[istate], self.relative_excitation_level[istate], is_converged, istate, self.system, self.options["amp_print_threshold"])
                print("   EOMCC calculation for root %d ended on" % istate, get_timestamp(), "\n")
        else:
            for j, istate in enumerate(state_index):
                print("   EOMCC calculation for root %d started on" % istate, get_timestamp())
                print("\n   Energy of initial guess = {:>10.10f}".format(self.vertical_excitation_energy[istate]))
                print_ee_amplitudes(self.R[istate], self.system, self.R[istate].order, self.options["amp_print_threshold"])
                # self.R[istate], self.vertical_excitation_energy[istate], is_converged = eomcc_davidson(HR_function, update_function, B0[:, j],
                #                                                                                        self.R[istate], dR, self.vertical_excitation_energy[istate],
                #                                                                                        self.T, self.hamiltonian, self.system, self.options)
                self.R[istate], self.vertical_excitation_energy[istate], is_converged = eomcc_davidson(HR_function, update_function,
                                                                                                       self.R[istate].flatten() / np.linalg.norm(self.R[istate].flatten()),
                                                                                                       self.R[istate], dR, self.vertical_excitation_energy[istate],
                                                                                                       self.T, self.hamiltonian, self.system, self.options)
                # Compute r0 a posteriori
                self.r0[istate] = get_r0(self.R[istate], self.hamiltonian, self.vertical_excitation_energy[istate])
                # compute the relative excitation level (REL) metric
                self.relative_excitation_level[istate] = get_rel(self.R[istate], self.r0[istate])
                eomcc_calculation_summary(self.R[istate], self.vertical_excitation_energy[istate], self.correlation_energy, self.r0[istate], self.relative_excitation_level[istate], is_converged, istate, self.system, self.options["amp_print_threshold"])
                print("   EOMCC calculation for root %d ended on" % istate, get_timestamp(), "\n")

    def run_sfeomcc(self, method, state_index):
        """Performs the SF-EOMCC calculation specified by the user in the input."""
        # check if requested CC calculation is implemented in modules
        if method.lower() not in ccpy.eomcc.MODULES:
            raise NotImplementedError(
                "{} not implemented".format(method.lower())
            )
        # Set operator parameters needed to build R
        self.set_operator_params(method)
        self.options["method"] = method.upper()

        # Ensure that Hbar is set upon entry
        assert (self.flag_hbar)

        # import the specific EOMCC method module and get its update function
        eom_module = import_module("ccpy.eomcc." + method.lower())
        HR_function = getattr(eom_module, 'HR')
        update_function = getattr(eom_module, 'update')

        for i in state_index:
            if self.R[i] is None:
                self.R[i] = SpinFlipOperator(self.system,
                                             Ms=-1,
                                             order=self.operator_params["order"])
                self.R[i].unflatten(self.guess_vectors[:, i], order=self.guess_order)
                self.vertical_excitation_energy[i] = self.guess_energy[i]

        # Form the initial subspace vectors
        # B0, _ = np.linalg.qr(np.asarray([self.R[i].flatten() for i in state_index]).T)

        # Print the options as a header
        self.print_options()

        # Create the residual R that is re-used for each root
        dR = SpinFlipOperator(self.system,
                              Ms=-1,
                              order=self.operator_params["order"])

        for j, istate in enumerate(state_index):
            print("   SF-EOMCC calculation for root %d started on" % istate, get_timestamp())
            print("\n   Energy of initial guess = {:>10.10f}".format(self.vertical_excitation_energy[istate]))
            print_sf_amplitudes(self.R[istate], self.system, self.R[istate].order, self.options["amp_print_threshold"])
            self.R[istate], self.vertical_excitation_energy[istate], is_converged = eomcc_davidson(HR_function,
                                                                                         update_function,
                                                                                         #B0[:, j],
                                                                                         self.R[istate].flatten() / np.linalg.norm(self.R[istate].flatten()),
                                                                                         self.R[istate], dR,
                                                                                         self.vertical_excitation_energy[istate],
                                                                                         self.T,
                                                                                         self.hamiltonian,
                                                                                         self.system,
                                                                                         self.options)
            sfeomcc_calculation_summary(self.R[istate], self.vertical_excitation_energy[istate], self.correlation_energy, is_converged, self.system, self.options["amp_print_threshold"])
            print("   SF-EOMCC calculation for root %d ended on" % istate, get_timestamp(), "\n")

    def run_deaeomcc(self, method, state_index):
        """Performs the particle-nonconserving DEA-EOMCC calculation specified by the user in the input."""
        # check if requested CC calculation is implemented in modules
        if method.lower() not in ccpy.eomcc.MODULES:
            raise NotImplementedError(
                "{} not implemented".format(method.lower())
            )
        # Set operator parameters needed to build R
        self.set_operator_params(method)
        self.options["method"] = method.upper()

        # Ensure that Hbar is set upon entry
        assert (self.flag_hbar)

        # import the specific EOMCC method module and get its update function
        eom_module = import_module("ccpy.eomcc." + method.lower())
        HR_function = getattr(eom_module, 'HR')
        update_function = getattr(eom_module, 'update')

        for i in state_index:
            if self.R[i] is None:
                self.R[i] = FockOperator(self.system,
                                         self.num_particles,
                                         self.num_holes)
                self.R[i].unflatten(self.guess_vectors[:, i], order=self.guess_order)
                self.vertical_excitation_energy[i] = self.guess_energy[i]

        # Form the initial subspace vectors
        # B0, _ = np.linalg.qr(np.asarray([self.R[i].flatten() for i in state_index]).T)

        # Print the options as a header
        self.print_options()

        # Create the residual R that is re-used for each root
        dR = FockOperator(self.system,
                          self.num_particles,
                          self.num_holes)

        for j, istate in enumerate(state_index):
            print("   DEA-EOMCC calculation for root %d started on" % istate, get_timestamp())
            print("\n   Energy of initial guess = {:>10.10f}".format(self.vertical_excitation_energy[istate]))
            print_dea_amplitudes(self.R[istate], self.system, self.R[istate].order, self.options["amp_print_threshold"])
            self.R[istate], self.vertical_excitation_energy[istate], is_converged = eomcc_davidson(HR_function,
                                                                                                   update_function,
                                                                                                   #B0[:, j],
                                                                                                   self.R[istate].flatten() / np.linalg.norm(self.R[istate].flatten()),
                                                                                                   self.R[istate],
                                                                                                   dR,
                                                                                                   self.vertical_excitation_energy[istate],
                                                                                                   self.T,
                                                                                                   self.hamiltonian,
                                                                                                   self.system,
                                                                                                   self.options)
            deaeomcc_calculation_summary(self.R[istate], self.vertical_excitation_energy[istate], self.correlation_energy, is_converged, self.system, self.options["amp_print_threshold"])
            print("   DEA-EOMCC calculation for root %d ended on" % istate, get_timestamp(), "\n")

    def run_ipeomcc(self, method, state_index):
        """Performs the particle-nonconserving IP-EOMCC calculation specified by the user in the input."""
        # check if requested CC calculation is implemented in modules
        if method.lower() not in ccpy.eomcc.MODULES:
            raise NotImplementedError(
                "{} not implemented".format(method.lower())
            )
        # Set operator parameters needed to build R
        self.set_operator_params(method)
        self.options["method"] = method.upper()

        # Ensure that Hbar is set upon entry
        assert (self.flag_hbar)

        # import the specific EOMCC method module and get its update function
        eom_module = import_module("ccpy.eomcc." + method.lower())
        HR_function = getattr(eom_module, 'HR')
        update_function = getattr(eom_module, 'update')

        for i in state_index:
            if self.R[i] is None:
                self.R[i] = FockOperator(self.system,
                                         self.num_particles,
                                         self.num_holes)
                self.R[i].unflatten(self.guess_vectors[:, i], order=self.guess_order)
                self.vertical_excitation_energy[i] = self.guess_energy[i]

        # Form the initial subspace vectors
        # B0, _ = np.linalg.qr(np.asarray([self.R[i].flatten() for i in state_index]).T)

        # Print the options as a header
        self.print_options()

        # Create the residual R that is re-used for each root
        dR = FockOperator(self.system,
                          self.num_particles,
                          self.num_holes)

        for j, istate in enumerate(state_index):
            print("   IP-EOMCC calculation for root %d started on" % istate, get_timestamp())
            print("\n   Energy of initial guess = {:>10.10f}".format(self.vertical_excitation_energy[istate]))
            print_ip_amplitudes(self.R[istate], self.system, self.R[istate].order, self.options["amp_print_threshold"])
            self.R[istate], self.vertical_excitation_energy[istate], is_converged = eomcc_davidson(HR_function,
                                                                                                   update_function,
                                                                                                   #B0[:, j],
                                                                                                   self.R[istate].flatten() / np.linalg.norm(self.R[istate].flatten()),
                                                                                                   self.R[istate],
                                                                                                   dR,
                                                                                                   self.vertical_excitation_energy[istate],
                                                                                                   self.T,
                                                                                                   self.hamiltonian,
                                                                                                   self.system,
                                                                                                   self.options)
            # compute the relative excitation level (REL) metric
            self.relative_excitation_level[istate] = get_rel_ip(self.R[istate])
            ipeomcc_calculation_summary(self.R[istate], self.vertical_excitation_energy[istate], self.correlation_energy, self.relative_excitation_level[istate], is_converged, self.system, self.options["amp_print_threshold"])
            print("   IP-EOMCC calculation for root %d ended on" % istate, get_timestamp(), "\n")

    def run_eaeomcc(self, method, state_index):
        """Performs the particle-nonconserving EA-EOMCC calculation specified by the user in the input."""
        # check if requested CC calculation is implemented in modules
        if method.lower() not in ccpy.eomcc.MODULES:
            raise NotImplementedError(
                "{} not implemented".format(method.lower())
            )
        # Set operator parameters needed to build R
        self.set_operator_params(method)
        self.options["method"] = method.upper()

        # Ensure that Hbar is set upon entry
        assert (self.flag_hbar)

        # import the specific EOMCC method module and get its update function
        eom_module = import_module("ccpy.eomcc." + method.lower())
        HR_function = getattr(eom_module, 'HR')
        update_function = getattr(eom_module, 'update')

        for i in state_index:
            if self.R[i] is None:
                self.R[i] = FockOperator(self.system,
                                         self.num_particles,
                                         self.num_holes)
                self.R[i].unflatten(self.guess_vectors[:, i], order=self.guess_order)
                self.vertical_excitation_energy[i] = self.guess_energy[i]

        # Form the initial subspace vectors
        # B0, _ = np.linalg.qr(np.asarray([self.R[i].flatten() for i in state_index]).T)

        # Print the options as a header
        self.print_options()

        # Create the residual R that is re-used for each root
        dR = FockOperator(self.system,
                          self.num_particles,
                          self.num_holes)

        for j, istate in enumerate(state_index):
            print("   EA-EOMCC calculation for root %d started on" % istate, get_timestamp())
            print("\n   Energy of initial guess = {:>10.10f}".format(self.vertical_excitation_energy[istate]))
            print_ea_amplitudes(self.R[istate], self.system, self.R[istate].order, self.options["amp_print_threshold"])
            self.R[istate], self.vertical_excitation_energy[istate], is_converged = eomcc_davidson(HR_function,
                                                                                                   update_function,
                                                                                                   #B0[:, j],
                                                                                                   self.R[istate].flatten() / np.linalg.norm(self.R[istate].flatten()),
                                                                                                   self.R[istate],
                                                                                                   dR,
                                                                                                   self.vertical_excitation_energy[istate],
                                                                                                   self.T,
                                                                                                   self.hamiltonian,
                                                                                                   self.system,
                                                                                                   self.options)
            # compute the relative excitation level (REL) metric
            self.relative_excitation_level[istate] = get_rel_ea(self.R[istate])
            eaeomcc_calculation_summary(self.R[istate], self.vertical_excitation_energy[istate], self.correlation_energy, self.relative_excitation_level[istate], is_converged, self.system, self.options["amp_print_threshold"])
            print("   EA-EOMCC calculation for root %d ended on" % istate, get_timestamp(), "\n")

    def run_leftcc(self, method, state_index=[0]):
        # check if requested CC calculation is implemented in modules
        if method.lower() not in ccpy.left.MODULES:
            raise NotImplementedError(
                "{} not implemented".format(method.lower())
            )
        # Set operator parameters needed to build L
        self.set_operator_params(method)
        self.options["method"] = method.upper()

        # Ensure that Hbar is set upon entry
        assert(self.flag_hbar)

        # import the specific CC method module and get its update function
        lcc_mod = import_module("ccpy.left." + method.lower())
        update_function = getattr(lcc_mod, 'update')

        LR_function = None

        # Print the options as a header
        self.print_options()

        # regardless of restart status, initialize residual anew
        LH = ClusterOperator(self.system,
                             order=self.operator_params["order"],
                             active_orders=self.operator_params["active_orders"],
                             num_active=self.operator_params["number_active_indices"])

        for i in state_index:
            print("   Left CC calculation for root %d started on" % i, get_timestamp())
            # decide whether this is a ground-state calculation
            if i == 0: 
                ground_state = True
            else:
                ground_state = False
                LR_function = lambda L, l3_excitations: get_LR(self.R[i], L, l3_excitations=None, r3_excitations=None)

            # Create either the standard CC cluster operator
            # initialize the left CC operator anew, or use restart
            if self.L[i] is None:
                self.L[i] = ClusterOperator(self.system,
                                            order=self.operator_params["order"],
                                            active_orders=self.operator_params["active_orders"],
                                            num_active=self.operator_params["number_active_indices"])
                # set initial value based on ground- or excited-state
                if ground_state:
                    self.L[i].unflatten(self.T.flatten()[:self.L[i].ndim])
                else:
                    self.L[i].unflatten(self.R[i].flatten())
            # Zero out the residual
            LH.unflatten(0.0 * LH.flatten())

            # Run the left CC calculation
            self.L[i], _, LR, is_converged = left_cc_jacobi(update_function, self.L[i], LH, self.T, self.hamiltonian,
                                                            LR_function, self.vertical_excitation_energy[i],
                                                            ground_state, self.system, self.options)

            if not ground_state:
                self.L[i].unflatten(1.0 / LR_function(self.L[i], None) * self.L[i].flatten())

            leftcc_calculation_summary(self.L[i], self.vertical_excitation_energy[i], LR, is_converged, self.system, self.options["amp_print_threshold"])
            print("   Left CC calculation for root %d ended on" % i, get_timestamp(), "\n")

    def run_lefteomcc(self, method, state_index):
        # check if requested CC calculation is implemented in modules
        if method.lower() not in ccpy.left.MODULES:
            raise NotImplementedError(
                "{} not implemented".format(method.lower())
            )
        # Set operator parameters needed to build L
        self.set_operator_params(method)
        self.options["method"] = method.upper()

        # Ensure that Hbar is set upon entry
        assert(self.flag_hbar)

        # import the specific CC method module and get its update function
        lcc_mod = import_module("ccpy.left." + method.lower())
        update_function = getattr(lcc_mod, 'update_l')
        LH_function = getattr(lcc_mod, "LH_fun")

        # Print the options as a header
        self.print_options()

        for i in state_index:
            # Create either the standard CC cluster operator
            if self.L[i] is None:
                self.L[i] = ClusterOperator(self.system,
                                            order=self.operator_params["order"],
                                            active_orders=self.operator_params["active_orders"],
                                            num_active=self.operator_params["number_active_indices"])
                self.L[i].unflatten(self.R[i].flatten())


        # Form the initial subspace vectors
        # B0, _ = np.linalg.qr(np.asarray([self.L[i].flatten() for i in state_index]).T)

        # Create the residual L*H that is re-used for each root
        LH = ClusterOperator(self.system,
                             order=self.operator_params["order"],
                             active_orders=self.operator_params["active_orders"],
                             num_active=self.operator_params["number_active_indices"])

        for j, istate in enumerate(state_index):
            print("   Left-EOMCC calculation for root %d started on" % istate, get_timestamp())
            print("\n   Energy of initial guess = {:>10.10f}".format(self.vertical_excitation_energy[istate]))
            print_ee_amplitudes(self.L[istate], self.system, self.L[istate].order, self.options["amp_print_threshold"])
            self.L[istate], self.vertical_excitation_energy[istate], is_converged = eomcc_davidson(LH_function,
                                                                                                   update_function,
                                                                                                   #B0[:, j],
                                                                                                   self.L[istate].flatten() / np.linalg.norm(self.L[istate].flatten()),
                                                                                                   self.L[istate],
                                                                                                   LH,
                                                                                                   self.vertical_excitation_energy[istate],
                                                                                                   self.T,
                                                                                                   self.hamiltonian,
                                                                                                   self.system,
                                                                                                   self.options)
            # Create the LR normalization function
            LR_function = lambda L: get_LR(self.R[istate], L, l3_excitations=None, r3_excitations=None)
            LR = LR_function(self.L[istate])
            self.L[istate].unflatten(1.0 / LR * self.L[istate].flatten())
            leftcc_calculation_summary(self.L[istate], self.vertical_excitation_energy[istate], LR, is_converged, self.system, self.options["amp_print_threshold"])
            print("   Left-EOMCC calculation for root %d ended on" % istate, get_timestamp(), "\n")

    def run_leftccp(self, method, t3_excitations, state_index=[0], r3_excitations=None, pspace=None):
        # check if requested CC calculation is implemented in modules
        if method.lower() not in ccpy.left.MODULES:
            raise NotImplementedError(
                "{} not implemented".format(method.lower())
            )
        # Set operator parameters needed to build L
        self.set_operator_params(method)
        self.options["method"] = method.upper()

        # Ensure that Hbar is set upon entry
        assert(self.flag_hbar)

        # import the specific CC method module and get its update function
        lcc_mod = import_module("ccpy.left." + method.lower())
        update_function = getattr(lcc_mod, 'update')

        LR_function = None

        # Print the options as a header
        self.print_options()

        # Convert excitations array to Fortran continuous
        t3_excitations = convert_excitations_c_to_f(t3_excitations)
        r3_excitations = convert_excitations_c_to_f(r3_excitations)

        for i in state_index:
            print("   Left CC(P) calculation for root %d started on" % i, get_timestamp())
            # decide whether this is a ground-state calculation
            if i == 0: 
                ground_state = True
            else:
                ground_state = False
                LR_function = lambda L, l3_excitations: get_LR(self.R[i], L, l3_excitations=l3_excitations, r3_excitations=r3_excitations)

            # Create either the CC(P) cluster operator
            # Get the l3_excitations list based on T (ground state) or R (excited states)
            if ground_state:
                l3_excitations = {"aaa" : t3_excitations["aaa"],
                                  "aab" : t3_excitations["aab"],
                                  "abb" : t3_excitations["abb"],
                                  "bbb" : t3_excitations["bbb"]}
            else:
                l3_excitations = {"aaa" : r3_excitations["aaa"],
                                  "aab" : r3_excitations["aab"],
                                  "abb" : r3_excitations["abb"],
                                  "bbb" : r3_excitations["bbb"]}

            n3aaa = l3_excitations["aaa"].shape[0]
            n3aab = l3_excitations["aab"].shape[0]
            n3abb = l3_excitations["abb"].shape[0]
            n3bbb = l3_excitations["bbb"].shape[0]
            excitation_count = [[n3aaa, n3aab, n3abb, n3bbb]]
            # If RHF, copy aab into abb and aaa in bbb; this is dangerous for left-CC(P) and EOMCC(P)
            # because open-shell like triplets can be targetted out of a singlet reference, so RHF_symmetry should
            # be false in those cases.
            # if self.options["RHF_symmetry"]:
            #     assert (n3aaa == n3bbb)
            #     assert (n3aab == n3abb)
            #     l3_excitations["bbb"] = l3_excitations["aaa"].copy()
            #     l3_excitations["abb"] = l3_excitations["aab"][:, [2, 0, 1, 5, 3, 4]]  # want abb excitations as a b~<c~ i j~<k~; MUST be this order!
            # Create the left CC(P) operator
            if self.L[i] is None:
                self.L[i] = ClusterOperator(self.system,
                                            order=self.operator_params["order"],
                                            p_orders=self.operator_params["pspace_orders"],
                                            pspace_sizes=excitation_count)
                # set initial value based on ground- or excited-state
                if ground_state:
                    self.L[i].unflatten(self.T.flatten())
                else:
                    self.L[i].unflatten(self.R[i].flatten())
            # Regardless of restart status, make LH anew. It could be of different length for different roots
            LH = ClusterOperator(self.system,
                                 order=self.operator_params["order"],
                                 p_orders=self.operator_params["pspace_orders"],
                                 pspace_sizes=excitation_count)
            # Zero out the residual
            LH.unflatten(0.0 * LH.flatten())

            # Run the left CC calculation
            self.L[i], _, LR, is_converged = left_cc_jacobi(update_function, self.L[i], LH, self.T, self.hamiltonian,
                                                            LR_function, self.vertical_excitation_energy[i],
                                                            ground_state, self.system, self.options,
                                                            t3_excitations, l3_excitations)

            if not ground_state:
                self.L[i].unflatten(1.0 / LR_function(self.L[i], l3_excitations) * self.L[i].flatten())
                # Reorder L to match the order of r3_excitations
                self.L[i] = reorder_triples_amplitudes(self.L[i], l3_excitations, r3_excitations)
            else:
                # Reorder L to match the order of t3_excitations
                self.L[i] = reorder_triples_amplitudes(self.L[i], l3_excitations, t3_excitations)

            leftcc_calculation_summary(self.L[i], self.vertical_excitation_energy[i], LR, is_converged, self.system, self.options["amp_print_threshold"])
            print("   Left CC(P) calculation for root %d ended on" % i, get_timestamp(), "\n")

    def run_lefteomccp(self, method, state_index, t3_excitations, r3_excitations):
        # check if requested CC calculation is implemented in modules
        if method.lower() not in ccpy.left.MODULES:
            raise NotImplementedError(
                "{} not implemented".format(method.lower())
            )
        # Set operator parameters needed to build L
        self.set_operator_params(method)
        self.options["method"] = method.upper()
        # Ensure that Hbar is set upon entry
        assert(self.flag_hbar)

        # import the specific CC method module and get its update function
        lcc_mod = import_module("ccpy.left." + method.lower())
        update_function = getattr(lcc_mod, 'update_l')
        LH_function = getattr(lcc_mod, "LH_fun")

        # Convert excitations array to Fortran continuous
        t3_excitations = convert_excitations_c_to_f(t3_excitations)
        r3_excitations = convert_excitations_c_to_f(r3_excitations)

        # Print the options as a header
        self.print_options()
        # Save the right eigenvalue
        omega_right = self.vertical_excitation_energy[state_index]

        # Get the l3_excitations list based R
        l3_excitations = {"aaa": r3_excitations["aaa"],
                          "aab": r3_excitations["aab"],
                          "abb": r3_excitations["abb"],
                          "bbb": r3_excitations["bbb"]}
        excitation_count = [[excits.shape[0] for _, excits in l3_excitations.items()]]
        # Create the left CC(P) operator
        if self.L[state_index] is None:
            self.L[state_index] = ClusterOperator(self.system,
                                                  order=self.operator_params["order"],
                                                  p_orders=self.operator_params["pspace_orders"],
                                                  pspace_sizes=excitation_count)
            # set initial value based on excited-state
            self.L[state_index].unflatten(self.R[state_index].flatten())

        # Form the initial subspace vector
        # B0, _ = np.linalg.qr(self.L[state_index].flatten()[:, np.newaxis])

        # Regardless of restart status, make LH anew. It could be of different length for different roots
        LH = ClusterOperator(self.system,
                             order=self.operator_params["order"],
                             p_orders=self.operator_params["pspace_orders"],
                             pspace_sizes=excitation_count)

        print("   Left-EOMCC(P) calculation for root %d started on" % state_index, get_timestamp())
        print("\n   Energy of initial guess = {:>10.10f}".format(self.vertical_excitation_energy[state_index]))
        print_ee_amplitudes(self.L[state_index], self.system, self.L[state_index].order, self.options["amp_print_threshold"])
        self.L[state_index], self.vertical_excitation_energy[state_index], is_converged = eomcc_davidson(LH_function,
                                                                                                         update_function,
                                                                                                         #B0[:, 0],
                                                                                                         self.L[state_index].flatten() / np.linalg.norm(self.L[state_index].flatten()),
                                                                                                         self.L[state_index],
                                                                                                         LH,
                                                                                                         self.vertical_excitation_energy[state_index],
                                                                                                         self.T,
                                                                                                         self.hamiltonian,
                                                                                                         self.system,
                                                                                                         self.options,
                                                                                                         t3_excitations,
                                                                                                         r3_excitations)
        # Compute L*R and normalize the computed left vector by LR
        LR = get_LR(self.R[state_index], self.L[state_index], l3_excitations=l3_excitations, r3_excitations=r3_excitations)
        self.L[state_index].unflatten(1.0 / LR * self.L[state_index].flatten())
        # Reorder L to match the order of r3_excitations
        self.L[state_index] = reorder_triples_amplitudes(self.L[state_index], l3_excitations, r3_excitations)
        leftcc_calculation_summary(self.L[state_index], self.vertical_excitation_energy[state_index], LR, is_converged, self.system, self.options["amp_print_threshold"])
        # Before leaving, verify that the excitation energy obtained in the left diagonalization matches
        print("   |ω(R) - ω(L)| = ", abs(omega_right - self.vertical_excitation_energy[state_index]))
        print("   Left-EOMCC(P) calculation for root %d ended on" % state_index, get_timestamp(), "\n")

    def run_leftipeomcc(self, method, state_index=[0], t3_excitations=None, r3_excitations=None):
        # check if requested CC calculation is implemented in modules
        if method.lower() not in ccpy.left.MODULES:
            raise NotImplementedError(
                "{} not implemented".format(method.lower())
            )
        # Set operator parameters needed to build L
        self.set_operator_params(method)
        self.options["method"] = method.upper()
        # Ensure that Hbar is set upon entry
        assert(self.flag_hbar)
        # import the specific CC method module and get its update function
        lcc_mod = import_module("ccpy.left." + method.lower())
        update_function = getattr(lcc_mod, 'update')
        # Print the options as a header
        self.print_options()
        # regardless of restart status, initialize residual anew for non-CC(P) cases
        LH = FockOperator(self.system,
                          self.num_particles,
                          self.num_holes)
        for i in state_index:
            print("   Left IP-EOMCC calculation for root %d started on" % i, get_timestamp())
            # decide whether this is a ground-state calculation
            ground_state = False
            LR_function = lambda L, l3_excitations: get_LR(self.R[i], L, l3_excitations=l3_excitations, r3_excitations=r3_excitations)
            # Create either the standard CC or CC(P) cluster operator
            if self.L[i] is None:
                self.L[i] = FockOperator(self.system,
                                         self.num_particles,
                                         self.num_holes)
                # set initial value based on ground- or excited-state
                self.L[i].unflatten(self.R[i].flatten())
            l3_excitations = None
            # Zero out the residual
            LH.unflatten(0.0 * LH.flatten())
            # Run the left CC calculation
            self.L[i], _, LR, is_converged = left_cc_jacobi(update_function, self.L[i], LH, self.T, self.hamiltonian,
                                                            LR_function, self.vertical_excitation_energy[i],
                                                            ground_state, self.system, self.options,
                                                            t3_excitations, l3_excitations)
            # Perform final biorthgonalization to R
            self.L[i].unflatten(1.0 / LR_function(self.L[i], l3_excitations) * self.L[i].flatten())
            leftcc_calculation_summary(self.L[i], self.vertical_excitation_energy[i], LR, is_converged, self.system, self.options["amp_print_threshold"])
            print("   Left IP-EOMCC calculation for root %d ended on" % i, get_timestamp(), "\n")

    def run_eccc(self, method, external_wavefunction, t3_excitations=None):
        from ccpy.extcorr.external_correction import cluster_analysis

        # Get the external T vector corresponding to the cluster analysis
        T_ext, VT_ext = cluster_analysis(external_wavefunction, self.hamiltonian, self.system)

        # check if requested CC calculation is implemented in modules
        if method.lower() not in ccpy.cc.MODULES:
            raise NotImplementedError(
                "{} not implemented".format(method.lower())
            )
        # Set operator parameters needed to build T
        self.set_operator_params(method)
        self.options["method"] = method.upper()

        # import the specific CC method module and get its update function
        cc_mod = import_module("ccpy.cc." + method.lower())
        update_function = getattr(cc_mod, 'update')

        # Print the options as a header
        print("   ec-CC calculation started on", get_timestamp())
        self.print_options()

        if self.T is None:
            self.T = ClusterOperator(self.system,
                                     order=self.operator_params["order"],
                                     active_orders=self.operator_params["active_orders"],
                                     num_active=self.operator_params["number_active_indices"])
            # Set the initial T1 and T2 components to that from cluster analysis
            setattr(self.T, 'a', T_ext.a)
            setattr(self.T, 'b', T_ext.b)
            setattr(self.T, 'aa', T_ext.aa)
            setattr(self.T, 'ab', T_ext.ab)
            setattr(self.T, 'bb', T_ext.bb)

        # regardless of restart status, initialize residual anew
        dT = ClusterOperator(self.system,
                             order=self.operator_params["order"],
                             active_orders=self.operator_params["active_orders"],
                             num_active=self.operator_params["number_active_indices"])
        # Run the CC calculation
        self.T, self.correlation_energy, _ = eccc_jacobi(update_function,
                                                  self.T,
                                                  dT,
                                                  self.hamiltonian,
                                                  T_ext, VT_ext,
                                                  self.system,
                                                  self.options,
                                               )

        cc_calculation_summary(self.T, self.system.reference_energy, self.correlation_energy, self.system, self.options["amp_print_threshold"])
        print("   ec-CC calculation ended on", get_timestamp())

    def run_ccp3(self, method, state_index=[0], two_body_approx=True, t3_excitations=None, l3_excitations=None, r3_excitations=None, pspace=None):

        if method.lower() == "crcc23":
            from ccpy.moments.crcc23 import calc_crcc23
            from ccpy.moments.creomcc23 import calc_creomcc23
            # Ensure that HBar is set upon entry
            assert(self.flag_hbar)
            for i in state_index:
                # Perform ground-state correction
                if i == 0:
                    _, self.deltap3[i] = calc_crcc23(self.T, self.L[i], self.correlation_energy, self.hamiltonian, self.fock, self.system, self.options["RHF_symmetry"])
                else:
                    # Perform excited-state corrections
                    _, self.deltap3[i], self.ddeltap3[i] = calc_creomcc23(self.T, self.R[i], self.L[i], self.r0[i],
                                                                          self.vertical_excitation_energy[i], self.correlation_energy, self.hamiltonian, self.fock,
                                                                          self.system, self.options["RHF_symmetry"])
        elif method.lower() == "ccsd(t)":
            from ccpy.moments.crcc23 import calc_ccsdpt
            # Ensure that only the bare Hamiltonian is used
            assert(not self.flag_hbar)
            _, self.deltap3[0] = calc_ccsdpt(self.T, self.correlation_energy, self.hamiltonian, self.system, self.options["RHF_symmetry"])

        elif method.lower() == "cct3":
            from ccpy.moments.cct3 import calc_cct3, calc_eomcct3
            from ccpy.hbar.hbar_ccsdt_p import remove_VT3_intermediates
            from ccpy.utilities.utilities import unravel_triples_amplitudes
            # Ensure that HBar is set
            assert self.flag_hbar
            for i in state_index:
                if i == 0:
                    # Perform ground-state correction
                    # WARNING: Set this value to [1] as a failsafe since CC(t;3) can also be run through CC(P) and left-CC(P) routines
                    if not self.operator_params["number_active_indices"]: self.operator_params["number_active_indices"] = [1]
                    # In order to use two-body approximation consistently for excited states, remove the V*T3 terms in vooo and vvov elements of HBar
                    if two_body_approx and t3_excitations:
                        self.hamiltonian = remove_VT3_intermediates(self.T, t3_excitations, self.hamiltonian)
                    if two_body_approx:
                        _, self.deltap3[0] = calc_cct3(self.T, self.L[0], self.correlation_energy, self.hamiltonian, self.fock, self.system,
                                                       self.options["RHF_symmetry"], num_active=self.operator_params["number_active_indices"])
                    elif not two_body_approx and t3_excitations: # perform full CC(t;3) correction using CC(P) routine
                        unravel_triples_amplitudes(self.T, t3_excitations)
                else:
                    # Perform excited-state correction
                    # WARNING: Set this value to [1] as a failsafe since EOMCC(t;3) is going to be run through EOMCC(P) and left-EOMCC(P) routines
                    if not self.operator_params["number_active_indices"]: self.operator_params["number_active_indices"] = [1]
                    # In order to use two-body approximation consistently for excited states, remove the V*T3 terms in vooo and vvov elements of HBar
                    if two_body_approx:
                        self.hamiltonian = remove_VT3_intermediates(self.T, t3_excitations, self.hamiltonian)
                    _, self.deltap3[i], self.ddeltap3[i] = calc_eomcct3(self.T, self.R[i], self.L[i], self.r0[i],
                                                                        self.vertical_excitation_energy[i], self.correlation_energy, self.hamiltonian, self.fock,
                                                                        self.system, self.options["RHF_symmetry"], num_active=self.operator_params["number_active_indices"])
        elif method.lower() == "ccp3":
            from ccpy.moments.ccp3 import calc_ccp3_2ba, calc_ccp3_full
            from ccpy.hbar.hbar_ccsdt_p import remove_VT3_intermediates
            from ccpy.utilities.utilities import unravel_triples_amplitudes
            # Ensure that both HBar is set
            assert self.flag_hbar

            # Reomve V*T3 from HBar if left-CC(P)/EOMCC(P) was performed and you want to use 2BA with CCSD HBar
            if two_body_approx and self.L[0].order > 2:
                self.hamiltonian = remove_VT3_intermediates(self.T, t3_excitations, self.hamiltonian)

            for i in state_index:
                # Ground-state correction
                if i == 0:
                    # Use the 2BA (requires only L1, L2 and HBar of CCSD)
                    if two_body_approx:
                        _, self.deltap3[0] = calc_ccp3_2ba(self.T, self.L[0], t3_excitations, self.correlation_energy, self.hamiltonian, self.fock, self.system, self.options["RHF_symmetry"])
                    # full correction (requires L1, L2, and L3 as well as HBar of CCSDt)
                    else:
                        # unravel triples vector into t3(abcijk) and l3(abcijk)
                        self.T = unravel_triples_amplitudes(self.T, t3_excitations)
                        self.L[0] = unravel_triples_amplitudes(self.L[0], t3_excitations)
                        _, self.deltap3[0] = calc_ccp3_full(self.T, self.L[0], t3_excitations, self.correlation_energy, self.hamiltonian, self.fock, self.system, self.options["RHF_symmetry"])
                # Excited-state corrections
                else:
                    pass

        # elif method.lower() == "ccp3(t)":
        #     from ccpy.moments.ccp3 import calc_ccpert3
        #     # Ensure that pspace is set
        #     assert pspace
        #     # Warn the user if they run using HBar instead of H; we will not disallow it, however
        #     if self.flag_hbar:
        #         print("WARNING: CC(P;3)_(T) is using similarity-transformed Hamiltonian! Results will not match conventional CCSD(T)!")
        #     # Perform ground-state correction
        #     _, self.deltap3[0] = calc_ccpert3(self.T, self.correlation_energy, self.hamiltonian, self.system, pspace, self.options["RHF_symmetry"])
        # else:
        #     raise NotImplementedError("Triples correction {} not implemented".format(method.lower()))

    def run_ccp4(self, method, state_index=[0], two_body_approx=True):

        if method.lower() == "crcc24":
            from ccpy.moments.crcc24 import calc_crcc24
            # Ensure that HBar is set
            assert self.flag_hbar
            # Perform ground-state correction
            _, self.deltap4[0] = calc_crcc24(self.T, self.L[0], self.correlation_energy, self.hamiltonian, self.fock, self.system, self.options["RHF_symmetry"])
        else:
            raise NotImplementedError("Quadruples correction {} not implemented".format(method.lower()))

    def run_rdm1(self, state_index=[0]):
        from ccpy.density.rdm1 import calc_rdm1
        for istate in state_index:
            for jstate in state_index:
                self.rdm1[istate][jstate] = calc_rdm1(self.T, self.L[istate], self.system)

# Legacy version of adaptive CC(P;Q) that includes CCSD(T) corrections and full moment selection options
# class AdaptDriver:
#
#     def __init__(self, driver, percentage, full_storage=False, perturbative=False, pspace_analysis=True, two_body_left=False):
#         from ccpy.utilities.pspace import get_empty_pspace
#         self.driver = driver
#         self.percentage = percentage
#         self.options = {"full storage": full_storage,
#                         "perturbative": perturbative,
#                         "P space analysis": pspace_analysis,
#                         "two_body_left": two_body_left}
#
#         self.nmacro = len(self.percentage)
#         self.ccp_energy = np.zeros(self.nmacro)
#         self.ccpq_energy = np.zeros(self.nmacro)
#         self.pspace = get_empty_pspace(self.driver.system, 3, use_bool=True)
#         self.t3_excitations = {"aaa": np.ones((1, 6), order="F"),
#                                "aab": np.ones((1, 6), order="F"),
#                                "abb": np.ones((1, 6), order="F"),
#                                "bbb": np.ones((1, 6), order="F")}
#
#         # Save the bare Hamiltonian for later iterations if using CR-CC(2,3)
#         # since H will get overwritten to HBar. When using CCSD(T), H never
#         # changes, so you don't need to do this.
#         if not self.options["perturbative"]:
#             self.bare_hamiltonian = deepcopy(self.driver.hamiltonian)
#
#     def print_options(self):
#         print("   ------------------------------------------")
#         for option_key, option_value in self.options.items():
#             print("  ", option_key, "=", option_value)
#         print("   ------------------------------------------\n")
#
#     def excitation_count(self):
#         """Performs an initial symmetry-adapted count of the triples excitation
#            space to determine the total number of triples and the relevant incremental
#            additions used throughout the calculation."""
#         from ccpy.utilities.symmetry import count_triples
#         # Count the triples using symmetry
#         self.num_excitations_symmetry, _ = count_triples(self.driver.system)
#         self.num_total_excitations = self.num_excitations_symmetry[self.driver.system.point_group_irrep_to_number[self.driver.system.reference_symmetry]]
#         self.one_increment = int(0.01 * self.num_total_excitations)
#         # Setting up the number of added determinants in each iteration
#         self.num_dets_to_add = np.zeros(len(self.percentage))
#         for i in range(len(self.percentage) - 1):
#             if self.percentage[i + 1] == 100.0:
#                 self.num_dets_to_add[i] = self.num_total_excitations - self.one_increment * self.percentage[i]
#             else:
#                 self.num_dets_to_add[i] = self.one_increment * (self.percentage[i + 1] - self.percentage[i])
#         self.num_dets_to_add[-1] = 1
#         # Adjust for RHF symmetry
#         if self.driver.options["RHF_symmetry"]:
#             for i in range(len(self.percentage) - 1):
#                 self.num_dets_to_add[i] = int(self.num_dets_to_add[i] / 2)
#
#     def analyze_pspace(self):
#         """Counts and analyzes the P space in terms of spatial and Sz-spin symmetry."""
#         from ccpy.utilities.pspace import count_excitations_in_pspace
#         # Count the excitations in the current P space
#         excitation_count = count_excitations_in_pspace(self.pspace, self.driver.system)
#
#         # The adaptive P spaces do not follow the same pattern of the CIPSI-generated P spaces
#         # is this just a difference in how CI vs. CC gets spin adapted or is this a problem?
#         # E.g., if the aaa and aab do not completely overlap, is S2 symmetry broken for RHF?
#         # Clearly at the CCSDT limit, this condition is filled, so spin symmetry is restored.
#         # noa, nob, nua, nub = self.bare_hamiltonian.ab.oovv.shape
#         # for a in range(nua):
#         #     for b in range(a + 1, nua):
#         #         for c in range(b + 1, nua):
#         #             for i in range(noa):
#         #                 for j in range(i + 1, noa):
#         #                     for k in range(j + 1, noa):
#         #                         if self.pspace["aaa"][a, b, c, i, j, k] == 1:
#         #                             if self.pspace["aab"][a, b, c, i, j, k] != 1:
#         #                                 print("aab VIOLATION")
#         #                             if self.pspace["bbb"][a, b, c, i, j, k] != 1:
#         #                                 print("bbb VIOLATION")
#         # noa, nob, nua, nub = self.bare_hamiltonian.ab.oovv.shape
#         # for a in range(nua):
#         #     for b in range(a + 1, nua):
#         #         for c in range(nub):
#         #             for i in range(noa):
#         #                 for j in range(i + 1, noa):
#         #                     for k in range(nob):
#         #                         if self.pspace["aab"][a, b, c, i, j, k] == 1:
#         #                             if self.pspace["abb"][c, a, b, k, i, j] != 1:
#         #                                 print("VIOLATION")
#
#     def run_ccp(self, imacro):
#         """Runs iterative CC(P), and if needed, HBar and iterative left-CC calculations."""
#         self.driver.run_ccp(method="ccsdt_p", t3_excitations=self.t3_excitations)
#         if not self.options["perturbative"]:
#             if self.options["two_body_left"]:
#                 self.driver.run_hbar(method="ccsd")
#                 self.driver.run_leftcc(method="left_ccsd")
#             else:
#                 self.driver.run_hbar(method="ccsdt_p", t3_excitations=self.t3_excitations)
#                 self.driver.run_leftccp(method="left_ccsdt_p", t3_excitations=self.t3_excitations)
#         self.ccp_energy[imacro] = self.driver.system.reference_energy + self.driver.correlation_energy
#
#     def run_ccp3(self, imacro):
#         """Runs the CC(P;3) correction using either the CR-CC(2,3)- or CCSD(T)-like approach,
#            while simultaneously selecting the leading triply excited determinants and returning
#            the result in an array. For the last calculation, this should not perform the
#            selection steps."""
#         from ccpy.moments.ccp3 import calc_ccp3_with_selection, calc_ccpert3_with_selection
#
#         if not self.options["perturbative"]: # CR-CC(2,3) method
#             if imacro < self.nmacro - 1:
#                 self.ccpq_energy[imacro], triples_list = calc_ccp3_with_selection(self.driver.T,
#                                                                                   self.driver.L[0],
#                                                                                   self.driver.correlation_energy,
#                                                                                   self.driver.hamiltonian,
#                                                                                   self.bare_hamiltonian,
#                                                                                   self.driver.system,
#                                                                                   self.pspace,
#                                                                                   self.num_dets_to_add[imacro],
#                                                                                   use_RHF=self.driver.options["RHF_symmetry"])
#             else:
#                 triples_list = []
#                 self.driver.run_ccp3(method="ccp3", state_index=[0], two_body_approx=True, pspace=self.pspace, t3_excitations=self.t3_excitations)
#                 self.ccpq_energy[imacro] = self.driver.system.reference_energy + self.driver.correlation_energy + self.driver.deltap3[0]["D"]
#         else: # CCSD(T) method
#             if imacro < self.nmacro - 1:
#                 self.ccpq_energy[imacro], triples_list = calc_ccpert3_with_selection(self.driver.T,
#                                                                                      self.driver.correlation_energy,
#                                                                                      self.driver.hamiltonian,
#                                                                                      self.driver.system,
#                                                                                      self.pspace,
#                                                                                      self.num_dets_to_add[imacro],
#                                                                                      use_RHF=self.driver.options["RHF_symmetry"])
#             else:
#                 triples_list = []
#                 self.driver.run_ccp3(method="ccp3(t)", state_index=[0], pspace=self.pspace)
#                 self.ccpq_energy[imacro] = self.driver.system.reference_energy + self.driver.correlation_energy + self.driver.deltap3[0]["A"]
#
#         return triples_list
#
#     def run_ccp3_fullstorage(self, imacro):
#         """Runs the CC(P;3) correction using either the CR-CC(2,3)- or CCSD(T)-like
#            approach and stores all moment corrections in one array in memory, which is later used
#            to identify the top determinants for inclusion in the P space.
#            For the last calculation, this should not perform the selection steps."""
#         from ccpy.moments.ccp3 import calc_ccp3_with_moments, calc_ccpert3_with_moments
#
#         if not self.options["perturbative"]: # CR-CC(2,3) method
#             if imacro < self.nmacro - 1:
#                 self.ccpq_energy[imacro], moments = calc_ccp3_with_moments(self.driver.T,
#                                                                            self.driver.L[0],
#                                                                            self.driver.correlation_energy,
#                                                                            self.driver.hamiltonian,
#                                                                            self.bare_hamiltonian,
#                                                                            self.driver.system,
#                                                                            self.pspace,
#                                                                            use_RHF=self.driver.options["RHF_symmetry"])
#             else:
#                 moments = []
#                 self.driver.run_ccp3(method="ccp3", state_index=[0], two_body_approx=True, pspace=self.pspace, t3_excitations=self.t3_excitations)
#                 self.ccpq_energy[imacro] = self.driver.system.reference_energy + self.driver.correlation_energy + self.driver.deltap3[0]["D"]
#         else: # CCSD(T) method
#             if imacro < self.nmacro - 1:
#                 self.ccpq_energy[imacro], moments = calc_ccpert3_with_moments(self.driver.T,
#                                                                               self.driver.correlation_energy,
#                                                                               self.driver.hamiltonian,
#                                                                               self.driver.system,
#                                                                               self.pspace,
#                                                                               use_RHF=self.driver.options["RHF_symmetry"])
#             else:
#                 moments = []
#                 self.driver.run_ccp3(method="ccp3(t)", state_index=[0], pspace=self.pspace)
#                 self.ccpq_energy[imacro] = self.driver.system.reference_energy + self.driver.correlation_energy + self.driver.deltap3[0]["A"]
#
#         return moments
#
#     def run_expand_pspace(self, imacro, moments_or_triples):
#         """This will expand the P space using the list of triply excited determinants identified
#            using the CC(P;Q) moment expansions, above."""
#         if self.options["full storage"]:
#             from ccpy.utilities.pspace import adaptive_triples_selection_from_moments
#             self.pspace, self.t3_excitations = adaptive_triples_selection_from_moments(moments_or_triples, self.pspace, self.t3_excitations, self.num_dets_to_add[imacro], self.driver.system, self.driver.options["RHF_symmetry"])
#         else:
#             from ccpy.utilities.pspace import add_spinorbital_triples_to_pspace
#             self.pspace, self.t3_excitations = add_spinorbital_triples_to_pspace(moments_or_triples, self.pspace, self.t3_excitations, self.driver.options["RHF_symmetry"])
#
#     def run(self):
#         """This is the main driver for the entire adaptive CC(P;Q) calculation. It will call the above
#            methods in the correct sequence and handle logic accordingly."""
#
#         # Print the options as a header
#         print("   Adaptive CC(P;Q) calculation started on", get_timestamp())
#         self.print_options()
#
#         # Step 0: Perform the preliminary excitation counting
#         print("   Preliminary excitation count...", end=" ")
#         t1 = time.perf_counter()
#         self.excitation_count()
#         print("completed in", time.perf_counter() - t1, "seconds")
#         print("   Excitation Count Summary:")
#         spin_fact = 1.0
#         if self.driver.options["RHF_symmetry"]:
#             spin_fact = 2.0
#         for i, count in enumerate(self.num_excitations_symmetry):
#             symmetry = self.driver.system.point_group_number_to_irrep[i]
#             print("      Symmetry", symmetry, " = ", count)
#         print("      Using", self.num_total_excitations, "as total for ground state.")
#         print("      Determinant addition plan:", [int("{0:.0f}".format(v, i)) for i, v in enumerate(self.num_dets_to_add[:-1] * spin_fact)])
#         print("")
#         for imacro in range(self.nmacro):
#             print("   Adaptive CC(P;Q) Macroiteration - ", imacro, "Fraction of triples = ", self.percentage[imacro], "%")
#             # Step 1: Analyze the P space (optional)
#             if self.options["P space analysis"]:
#                 self.analyze_pspace()
#             # Step 2: Run CC(P) on this P space
#             self.run_ccp(imacro)
#             # Step 3: Moment correction + adaptive selection
#             if self.options["full storage"]:
#                 selection_arr = self.run_ccp3_fullstorage(imacro)
#             else:
#                 selection_arr = self.run_ccp3(imacro)
#
#             # Print the change in CC(P) and CC(P;Q) energies
#             if imacro > 0:
#                 print("   Change in CC(P) energy = ", self.ccp_energy[imacro] - self.ccp_energy[imacro - 1])
#                 print("   Change in CC(P;Q) energy = ", self.ccpq_energy[imacro] - self.ccpq_energy[imacro - 1], "\n")
#             if imacro == self.nmacro - 1:
#                 break
#
#             # Step 4: Expand the P space
#             self.run_expand_pspace(imacro, selection_arr)
#             # Step 5: Reset variables in driver (CAN WE AVOID DOING THIS, PLEASE?)
#             self.driver.T = None
#             if not self.options["perturbative"]:
#                 self.driver.L[0] = None
#                 setattr(self.driver, "hamiltonian", self.bare_hamiltonian)
#
#         # Print results
#         print("   Adaptive CC(P;Q) calculation ended on", get_timestamp(), "\n")
#         print("   Summary of results:")
#         print("    %T           E(P)              E(P;Q)")
#         print("   ------------------------------------------")
#         for i in range(self.nmacro):
#             print("   %3.2f    %.10f     %.10f" % (self.percentage[i], self.ccp_energy[i], self.ccpq_energy[i]))
#
# class AdaptEOMDriver:
#
#     def __init__(self, driver, percentage, state_index, guess_method, roots_per_irrep, nact_occupied=0, nact_unoccupied=0, pspace_analysis=True):
#         from ccpy.utilities.pspace import get_empty_pspace
#         self.driver = driver
#         self.percentage = percentage
#         self.state_index = state_index
#         self.options = {"P space analysis": pspace_analysis,
#                         "Guess method": guess_method,
#                         "Roots per irrep": roots_per_irrep,
#                         "nact_occupied": nact_occupied,
#                         "nact_unoccupied": nact_unoccupied}
#
#         self.nmacro = len(self.percentage)
#         self.ccp_energy = [np.zeros(self.nmacro), np.zeros(self.nmacro)]
#         self.ccpq_energy = [np.zeros(self.nmacro), np.zeros(self.nmacro)]
#         self.pspace = [get_empty_pspace(self.driver.system, 3, use_bool=True), get_empty_pspace(self.driver.system, 3, use_bool=True)]
#         self.t3_excitations = {"aaa": np.ones((1, 6), order="F"),
#                                "aab": np.ones((1, 6), order="F"),
#                                "abb": np.ones((1, 6), order="F"),
#                                "bbb": np.ones((1, 6), order="F")}
#         self.r3_excitations = {"aaa": np.ones((1, 6), order="F"),
#                                "aab": np.ones((1, 6), order="F"),
#                                "abb": np.ones((1, 6), order="F"),
#                                "bbb": np.ones((1, 6), order="F")}
#
#         # Save the bare Hamiltonian for later iterations
#         self.bare_hamiltonian = deepcopy(self.driver.hamiltonian)
#
#     def print_options(self):
#         print("   ------------------------------------------")
#         for option_key, option_value in self.options.items():
#             print("  ", option_key, "=", option_value)
#         print("   ------------------------------------------\n")
#
#     # [TODO]: Change this to use symmetries other than ground-state symmetry
#     def excitation_count(self):
#         """Performs an initial symmetry-adapted count of the triples excitation
#            space to determine the total number of triples and the relevant incremental
#            additions used throughout the calculation."""
#         from ccpy.utilities.symmetry import count_triples
#         # Count the triples using symmetry
#         self.num_excitations_symmetry, _ = count_triples(self.driver.system)
#         self.num_total_excitations = self.num_excitations_symmetry[self.driver.system.point_group_irrep_to_number[self.driver.system.reference_symmetry]]
#         self.one_increment = int(0.01 * self.num_total_excitations)
#         # Setting up the number of added determinants in each iteration
#         self.num_dets_to_add = np.zeros(len(self.percentage))
#         for i in range(len(self.percentage) - 1):
#             if self.percentage[i + 1] == 100.0:
#                 self.num_dets_to_add[i] = self.num_total_excitations - self.one_increment * self.percentage[i]
#             else:
#                 self.num_dets_to_add[i] = self.one_increment * (self.percentage[i + 1] - self.percentage[i])
#         self.num_dets_to_add[-1] = 1
#         # Adjust for RHF symmetry
#         if self.driver.options["RHF_symmetry"]:
#             for i in range(len(self.percentage) - 1):
#                 self.num_dets_to_add[i] = int(self.num_dets_to_add[i] / 2)
#
#     def analyze_pspace(self):
#         """Counts and analyzes the P space in terms of spatial and Sz-spin symmetry."""
#         from ccpy.utilities.pspace import count_excitations_in_pspace
#         # Count the excitations in the current P space
#         print("   Ground State")
#         print("   ------------")
#         excitation_count = count_excitations_in_pspace(self.pspace[0], self.driver.system)
#         print("   Excited State")
#         print("   --------------")
#         excitation_count = count_excitations_in_pspace(self.pspace[1], self.driver.system)
#
#     def run_ccp(self, imacro):
#         """Runs iterative CC(P) and EOMCC(P) calculations."""
#         # Run ground-state CC(P)
#         self.driver.run_ccp(method="ccsdt_p", t3_excitations=self.t3_excitations)
#         self.driver.run_hbar(method="ccsdt_p", t3_excitations=self.t3_excitations)
#         self.driver.run_leftccp(method="left_ccsdt_p", t3_excitations=self.t3_excitations)
#         self.ccp_energy[0][imacro] = self.driver.system.reference_energy + self.driver.correlation_energy
#         # Run excited-state EOMCC(P)
#         self.driver.run_guess(method=self.options["Guess method"],
#                               roots_per_irrep=self.options["Roots per irrep"],
#                               nact_occupied=self.options["nact_occupied"],
#                               nact_unoccupied=self.options["nact_unoccupied"])
#         self.driver.run_eomccp(method="eomccsdt_p", state_index=self.state_index, t3_excitations=self.t3_excitations, r3_excitations=self.r3_excitations)
#         self.driver.run_lefteomccp(method="left_ccsdt_p", state_index=self.state_index, t3_excitations=self.t3_excitations, r3_excitations=self.r3_excitations)
#         self.ccp_energy[1][imacro] = self.driver.system.reference_energy + self.driver.correlation_energy + self.driver.vertical_excitation_energy[self.state_index]
#
#     def run_ccp3(self, imacro):
#         """Runs the CC(P;3) correction using either the CR-CC(2,3)- or CCSD(T)-like approach,
#            while simultaneously selecting the leading triply excited determinants and returning
#            the result in an array. For the last calculation, this should not perform the
#            selection steps."""
#         from ccpy.moments.ccp3 import calc_ccp3_with_selection
#
#         self.ccpq_energy[0][imacro], triples_list = calc_ccp3_with_selection(self.driver.T,
#                                                                           self.driver.L[0],
#                                                                           self.driver.correlation_energy,
#                                                                           self.driver.hamiltonian,
#                                                                           self.bare_hamiltonian,
#                                                                           self.driver.system,
#                                                                           self.pspace,
#                                                                           self.num_dets_to_add[imacro],
#                                                                           use_RHF=self.driver.options["RHF_symmetry"])
#
#         return triples_list
#
#     def run_expand_pspace(self, imacro, moments_or_triples):
#         """This will expand the P space using the list of triply excited determinants identified
#            using the CC(P;Q) moment expansions, above."""
#         from ccpy.utilities.pspace import add_spinorbital_triples_to_pspace
#         self.pspace, self.t3_excitations = add_spinorbital_triples_to_pspace(moments_or_triples, self.pspace, self.t3_excitations, self.driver.options["RHF_symmetry"])
#
#     def run(self):
#         """This is the main driver for the entire adaptive CC(P;Q) calculation. It will call the above
#            methods in the correct sequence and handle logic accordingly."""
#
#         # Print the options as a header
#         print("   Adaptive EOMCC(P;Q) calculation started on", get_timestamp())
#         self.print_options()
#
#         # Step 0: Perform the preliminary excitation counting
#         print("   Preliminary excitation count...", end=" ")
#         t1 = time.perf_counter()
#         self.excitation_count()
#         print("completed in", time.perf_counter() - t1, "seconds")
#         print("   Excitation Count Summary:")
#         spin_fact = 1.0
#         if self.driver.options["RHF_symmetry"]:
#             spin_fact = 2.0
#         for i, count in enumerate(self.num_excitations_symmetry):
#             symmetry = self.driver.system.point_group_number_to_irrep[i]
#             print("      Symmetry", symmetry, " = ", count)
#         print("      Using", self.num_total_excitations, "as total for ground state.")
#         print("      Determinant addition plan:", [int("{0:.0f}".format(v, i)) for i, v in enumerate(self.num_dets_to_add[:-1] * spin_fact)])
#         print("")
#         for imacro in range(self.nmacro):
#             print("   Adaptive CC(P;Q) Macroiteration - ", imacro, "Fraction of triples = ", self.percentage[imacro], "%")
#             # Step 1: Analyze the P space (optional)
#             if self.options["P space analysis"]:
#                 self.analyze_pspace()
#             # Step 2: Run CC(P) on this P space
#             self.run_ccp(imacro)
#             # Step 3: Moment correction + adaptive selection
#             selection_arr = self.run_ccp3(imacro)
#
#             # Print the change in CC(P) and CC(P;Q) energies
#             if imacro > 0:
#                 print("   Change in CC(P) energy = ", self.ccp_energy[imacro] - self.ccp_energy[imacro - 1])
#                 print("   Change in CC(P;Q) energy = ", self.ccpq_energy[imacro] - self.ccpq_energy[imacro - 1], "\n")
#             if imacro == self.nmacro - 1:
#                 break
#
#             # Step 4: Expand the P space
#             self.run_expand_pspace(imacro, selection_arr)
#             # Step 5: Reset variables in driver (CAN WE AVOID DOING THIS, PLEASE?)
#             self.driver.T = None
#             if not self.options["perturbative"]:
#                 self.driver.L[0] = None
#                 setattr(self.driver, "hamiltonian", self.bare_hamiltonian)
#
#         # Print results
#         print("   Adaptive CC(P;Q) calculation ended on", get_timestamp(), "\n")
#         print("   Summary of results:")
#         print("    %T           E(P)              E(P;Q)")
#         print("   ------------------------------------------")
#         for i in range(self.nmacro):
#             print("   %3.2f    %.10f     %.10f" % (self.percentage[i], self.ccp_energy[i], self.ccpq_energy[i]))



# def mrcc_driver(calculation, system, hamiltonian, model_space, two_body_approximation=True):
#     """Performs the calculation specified by the user in the input."""
#
#     # check if requested CC calculation is implemented in modules
#     if calculation.calculation_type not in ccpy.mrcc.MODULES:
#         raise NotImplementedError(
#             "{} not implemented".format(calculation.calculation_type)
#         )
#
#     # import the specific CC method module and get its update function
#     cc_mod = import_module("ccpy.mrcc." + calculation.calculation_type.lower())
#     heff_mod = import_module("ccpy.mrcc.effective_hamiltonian")
#     update_function = getattr(cc_mod, 'update')
#
#     if two_body_approximation: # use the Heff matrix elements computed using T(p) = T1(p) + T2(p)
#         compute_Heff_function = getattr(heff_mod, 'compute_Heff_mkmrccsd')
#     else:
#         compute_Heff_function = getattr(heff_mod, 'compute_Heff_' + calculation.calculation_type.lower())
#
#     cc_printer = CCPrinter(calculation)
#     cc_printer.cc_header()
#
#     # initialize the cluster operator anew, or use restart
#     # one used in the calculation. For example, we could not start a CCSDT
#     # calculation using the CCSD cluster amplitudes.
#     T = [None for i in range(len(model_space))]
#     dT = [None for i in range(len(model_space))]
#     for p in range(len(model_space)):
#         if T[p] is None:
#             T[p] = ClusterOperator(system,
#                                 order=calculation.order,
#                                 active_orders=calculation.active_orders,
#                                 num_active=calculation.num_active)
#
#         # regardless of restart status, initialize residual anew
#         dT[p] = ClusterOperator(system,
#                             order=calculation.order,
#                             active_orders=calculation.active_orders,
#                             num_active=calculation.num_active)
#
#     T, total_energy, is_converged = mrcc_jacobi(
#                                            update_function,
#                                            compute_Heff_function,
#                                            T,
#                                            dT,
#                                            model_space,
#                                            hamiltonian,
#                                            calculation,
#                                            system,
#                                            )
#
#
#     #total_energy = system.reference_energy + corr_energy
#
#     #cc_printer.cc_calculation_summary(system.reference_energy, corr_energy)
#
#     return T, total_energy, is_converged
