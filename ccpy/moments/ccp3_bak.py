"""Functions to calculate the ground-state CC(t;3) triples correction to CCSDt."""
import time

import numpy as np
from ccpy.hbar.diagonal import aaa_H3_aaa_diagonal, abb_H3_abb_diagonal, aab_H3_aab_diagonal, bbb_H3_bbb_diagonal
from ccpy.utilities.updates import ccp3_loops, ccp3_opt_loops, ccsdpt_loops, ccp3_adaptive_loops
from ccpy.left.left_cc_intermediates import build_left_ccsdt_intermediates


def calc_ccp3_full(T, L, t3_excitations, corr_energy, H, H0, system, use_RHF=False):
    """
    Calculate the ground-state CC(P;3) correction to the CC(P) energy.
    """
    t_start = time.perf_counter()

    # get the Hbar 3-body diagonal
    d3aaa_v, d3aaa_o = aaa_H3_aaa_diagonal(T, H, system)
    d3aab_v, d3aab_o = aab_H3_aab_diagonal(T, H, system)
    d3abb_v, d3abb_o = abb_H3_abb_diagonal(T, H, system)
    d3bbb_v, d3bbb_o = bbb_H3_bbb_diagonal(T, H, system)

    # get LT intermediates
    X = build_left_ccsdt_intermediates(L, T, system)

    #### aaa correction ####
    MM23A = build_M3A_full(T, H, H0)
    L3A = build_L3A_full(L, H, X)
    dA_aaa, dB_aaa, dC_aaa, dD_aaa = ccp3_loops.ccp3_loops.ccp3a_full(
        t3_excitations,
        MM23A, L3A, 0.0,
        H0.a.oo, H0.a.vv, H.a.oo, H.a.vv,
        H.aa.voov, H.aa.oooo, H.aa.vvvv,
        d3aaa_o, d3aaa_v,
        system.noccupied_alpha, system.nunoccupied_alpha,
    )

    #### aab correction ####
    MM23B = build_M3B_full(T, H, H0)
    L3B = build_L3B_full(L, H, X)
    dA_aab, dB_aab, dC_aab, dD_aab = ccp3_loops.ccp3_loops.ccp3b_full(
        t3_excitations,
        MM23B, L3B, 0.0,
        H0.a.oo, H0.a.vv, H0.b.oo, H0.b.vv,
        H.a.oo, H.a.vv, H.b.oo, H.b.vv,
        H.aa.voov, H.aa.oooo, H.aa.vvvv,
        H.ab.ovov, H.ab.vovo,
        H.ab.oooo, H.ab.vvvv,
        H.bb.voov,
        d3aaa_o, d3aaa_v, d3aab_o, d3aab_v, d3abb_o, d3abb_v,
        system.noccupied_alpha, system.nunoccupied_alpha,
        system.noccupied_beta, system.nunoccupied_beta,
    )

    if use_RHF:
        correction_A = 2.0 * dA_aaa + 2.0 * dA_aab
        correction_B = 2.0 * dB_aaa + 2.0 * dB_aab
        correction_C = 2.0 * dC_aaa + 2.0 * dC_aab
        correction_D = 2.0 * dD_aaa + 2.0 * dD_aab

    t_end = time.perf_counter()
    minutes, seconds = divmod(t_end - t_start, 60)

    energy_A = corr_energy + correction_A
    energy_B = corr_energy + correction_B
    energy_C = corr_energy + correction_C
    energy_D = corr_energy + correction_D

    total_energy_A = system.reference_energy + energy_A
    total_energy_B = system.reference_energy + energy_B
    total_energy_C = system.reference_energy + energy_C
    total_energy_D = system.reference_energy + energy_D

    print('   CC(P;3) Calculation Summary')
    print('   -------------------------------------')
    print("   Completed in  ({:0.2f}m  {:0.2f}s)\n".format(minutes, seconds))
    print("   CC(P) = {:>10.10f}".format(system.reference_energy + corr_energy))
    print(
        "   CC(P;3)_A = {:>10.10f}     ΔE_A = {:>10.10f}     δ_A = {:>10.10f}".format(
            total_energy_A, energy_A, correction_A
        )
    )
    print(
        "   CC(P;3)_B = {:>10.10f}     ΔE_B = {:>10.10f}     δ_B = {:>10.10f}".format(
            total_energy_B, energy_B, correction_B
        )
    )
    print(
        "   CC(P;3)_C = {:>10.10f}     ΔE_C = {:>10.10f}     δ_C = {:>10.10f}".format(
            total_energy_C, energy_C, correction_C
        )
    )
    print(
        "   CC(P;3)_D = {:>10.10f}     ΔE_D = {:>10.10f}     δ_D = {:>10.10f}\n".format(
            total_energy_D, energy_D, correction_D
        )
    )

    Eccp3 = {"A": total_energy_A, "B": total_energy_B, "C": total_energy_C, "D": total_energy_D}
    deltap3 = {"A": correction_A, "B": correction_B, "C": correction_C, "D": correction_D}

    return Eccp3, deltap3


# def calc_ccp3_2ba(T, L, corr_energy, H, H0, system, pspace, use_RHF=False):
#     """
#     Calculate the ground-state CC(P;3) correction to the CC(P) energy.
#     """
#     t_start = time.perf_counter()
#
#     # get the Hbar 3-body diagonal
#     d3aaa_v, d3aaa_o = aaa_H3_aaa_diagonal(T, H, system)
#     d3aab_v, d3aab_o = aab_H3_aab_diagonal(T, H, system)
#     d3abb_v, d3abb_o = abb_H3_abb_diagonal(T, H, system)
#     d3bbb_v, d3bbb_o = bbb_H3_bbb_diagonal(T, H, system)
#
#     #### aaa correction ####
#     # calculate intermediates
#     I2A_vvov = H.aa.vvov + np.einsum("me,abim->abie", H.a.ov, T.aa, optimize=True)
#     # perform correction in-loop
#     dA_aaa, dB_aaa, dC_aaa, dD_aaa = ccp3_loops.ccp3_loops.crcc23a_p(
#             pspace['aaa'],
#             T.aa, L.a, L.aa,
#             H.aa.vooo, I2A_vvov, H.aa.oovv, H.a.ov,
#             H.aa.vovv, H.aa.ooov, H0.a.oo, H0.a.vv,
#             H.a.oo, H.a.vv, H.aa.voov, H.aa.oooo,
#             H.aa.vvvv,
#             d3aaa_o, d3aaa_v,
#             system.noccupied_alpha, system.nunoccupied_alpha,
#     )
#
#     #### aab correction ####
#     # calculate intermediates
#     I2B_ovoo = H.ab.ovoo - np.einsum("me,ecjk->mcjk", H.a.ov, T.ab, optimize=True)
#     I2B_vooo = H.ab.vooo - np.einsum("me,aeik->amik", H.b.ov, T.ab, optimize=True)
#     I2A_vooo = H.aa.vooo - np.einsum("me,aeij->amij", H.a.ov, T.aa, optimize=True)
#
#     dA_aab, dB_aab, dC_aab, dD_aab = ccp3_loops.ccp3_loops.crcc23b_p(
#             pspace['aab'],
#             T.aa, T.ab, L.a, L.b, L.aa, L.ab,
#             I2B_ovoo, I2B_vooo, I2A_vooo,
#             H.ab.vvvo, H.ab.vvov, H.aa.vvov,
#             H.ab.vovv, H.ab.ovvv, H.aa.vovv,
#             H.ab.ooov, H.ab.oovo, H.aa.ooov,
#             H.a.ov, H.b.ov, H.aa.oovv, H.ab.oovv,
#             H0.a.oo, H0.a.vv, H0.b.oo, H0.b.vv,
#             H.a.oo, H.a.vv, H.b.oo, H.b.vv,
#             H.aa.voov, H.aa.oooo, H.aa.vvvv, H.ab.ovov,
#             H.ab.vovo, H.ab.oooo, H.ab.vvvv, H.bb.voov,
#             d3aaa_o, d3aaa_v, d3aab_o, d3aab_v, d3abb_o, d3abb_v,
#             system.noccupied_alpha, system.nunoccupied_alpha,
#             system.noccupied_beta, system.nunoccupied_beta,
#     )
#
#     if use_RHF:
#         correction_A = 2.0 * dA_aaa + 2.0 * dA_aab
#         correction_B = 2.0 * dB_aaa + 2.0 * dB_aab
#         correction_C = 2.0 * dC_aaa + 2.0 * dC_aab
#         correction_D = 2.0 * dD_aaa + 2.0 * dD_aab
#     else:
#         I2B_vooo = H.ab.vooo - np.einsum("me,aeij->amij", H.b.ov, T.ab, optimize=True)
#         I2C_vooo = H.bb.vooo - np.einsum("me,cekj->cmkj", H.b.ov, T.bb, optimize=True)
#         I2B_ovoo = H.ab.ovoo - np.einsum("me,ebij->mbij", H.a.ov, T.ab, optimize=True)
#
#         dA_abb, dB_abb, dC_abb, dD_abb = ccp3_loops.ccp3_loops.crcc23c_p(
#                 pspace['abb'],
#                 T.ab, T.bb, L.a, L.b, L.ab, L.bb,
#                 I2B_vooo, I2C_vooo, I2B_ovoo,
#                 H.ab.vvov, H.bb.vvov, H.ab.vvvo, H.ab.ovvv,
#                 H.ab.vovv, H.bb.vovv, H.ab.oovo, H.ab.ooov,
#                 H.bb.ooov,
#                 H.a.ov, H.b.ov,
#                 H.ab.oovv, H.bb.oovv,
#                 H0.a.oo, H0.a.vv, H0.b.oo, H0.b.vv,
#                 H.a.oo, H.a.vv, H.b.oo, H.b.vv,
#                 H.aa.voov, H.ab.ovov, H.ab.vovo, H.ab.oooo,
#                 H.ab.vvvv, H.bb.voov, H.bb.oooo, H.bb.vvvv,
#                 d3aab_o, d3aab_v, d3abb_o, d3abb_v, d3bbb_o, d3bbb_v,
#                 system.noccupied_alpha, system.nunoccupied_alpha,
#                 system.noccupied_beta, system.nunoccupied_beta,
#         )
#
#         I2C_vvov = H.bb.vvov + np.einsum("me,abim->abie", H.b.ov, T.bb, optimize=True)
#
#         dA_bbb, dB_bbb, dC_bbb, dD_bbb = ccp3_loops.ccp3_loops.crcc23d_p(
#                 pspace['bbb'],
#                 T.bb, L.b, L.bb,
#                 H.bb.vooo, I2C_vvov, H.bb.oovv, H.b.ov,
#                 H.bb.vovv, H.bb.ooov, H0.b.oo, H0.b.vv,
#                 H.b.oo, H.b.vv, H.bb.voov, H.bb.oooo, H.bb.vvvv,
#                 d3bbb_o, d3bbb_v,
#                 system.noccupied_beta, system.nunoccupied_beta,
#         )
#
#         correction_A = dA_aaa + dA_aab + dA_abb + dA_bbb
#         correction_B = dB_aaa + dB_aab + dB_abb + dB_bbb
#         correction_C = dC_aaa + dC_aab + dC_abb + dC_bbb
#         correction_D = dD_aaa + dD_aab + dD_abb + dD_bbb
#
#     t_end = time.perf_counter()
#     minutes, seconds = divmod(t_end - t_start, 60)
#
#     energy_A = corr_energy + correction_A
#     energy_B = corr_energy + correction_B
#     energy_C = corr_energy + correction_C
#     energy_D = corr_energy + correction_D
#
#     total_energy_A = system.reference_energy + energy_A
#     total_energy_B = system.reference_energy + energy_B
#     total_energy_C = system.reference_energy + energy_C
#     total_energy_D = system.reference_energy + energy_D
#
#     print('   CC(P;3) Calculation Summary')
#     print('   -------------------------------------')
#     print("   Completed in  ({:0.2f}m  {:0.2f}s)\n".format(minutes, seconds))
#     print("   CC(P) = {:>10.10f}".format(system.reference_energy + corr_energy))
#     print(
#         "   CC(P;3)_A = {:>10.10f}     ΔE_A = {:>10.10f}     δ_A = {:>10.10f}".format(
#             total_energy_A, energy_A, correction_A
#         )
#     )
#     print(
#         "   CC(P;3)_B = {:>10.10f}     ΔE_B = {:>10.10f}     δ_B = {:>10.10f}".format(
#             total_energy_B, energy_B, correction_B
#         )
#     )
#     print(
#         "   CC(P;3)_C = {:>10.10f}     ΔE_C = {:>10.10f}     δ_C = {:>10.10f}".format(
#             total_energy_C, energy_C, correction_C
#         )
#     )
#     print(
#         "   CC(P;3)_D = {:>10.10f}     ΔE_D = {:>10.10f}     δ_D = {:>10.10f}\n".format(
#             total_energy_D, energy_D, correction_D
#         )
#     )
#
#     Eccp3 = {"A": total_energy_A, "B": total_energy_B, "C": total_energy_C, "D": total_energy_D}
#     deltap3 = {"A": correction_A, "B": correction_B, "C": correction_C, "D": correction_D}
#
#     return Eccp3, deltap3

def calc_ccp3_2ba(T, L, t3_excitations, corr_energy, H, H0, system, use_RHF=False):
    """
    Calculate the ground-state CC(P;3) correction to the CC(P) energy in a
    memory-optimized manner that avoids the usage of the large logical P space
    array. Input T and L are in the same order and match with t3_excitations.
    """
    t_start = time.perf_counter()

    # get the Hbar 3-body diagonal
    d3aaa_v, d3aaa_o = aaa_H3_aaa_diagonal(T, H, system)
    d3aab_v, d3aab_o = aab_H3_aab_diagonal(T, H, system)
    d3abb_v, d3abb_o = abb_H3_abb_diagonal(T, H, system)
    d3bbb_v, d3bbb_o = bbb_H3_bbb_diagonal(T, H, system)

    #### aaa correction ####
    # calculate intermediates
    I2A_vvov = H.aa.vvov + np.einsum("me,abim->abie", H.a.ov, T.aa, optimize=True)
    # perform correction in-loop
    dA_aaa, dB_aaa, dC_aaa, dD_aaa = ccp3_opt_loops.ccp3_opt_loops.ccp3a_2ba(
            t3_excitations["aaa"].T,
            T.aa, L.a, L.aa,
            H.aa.vooo, I2A_vvov, H.aa.oovv, H.a.ov,
            H.aa.vovv, H.aa.ooov, H0.a.oo, H0.a.vv,
            H.a.oo, H.a.vv, H.aa.voov, H.aa.oooo,
            H.aa.vvvv,
            d3aaa_o, d3aaa_v,
    )
    #### aab correction ####
    # calculate intermediates
    I2B_ovoo = H.ab.ovoo - np.einsum("me,ecjk->mcjk", H.a.ov, T.ab, optimize=True)
    I2B_vooo = H.ab.vooo - np.einsum("me,aeik->amik", H.b.ov, T.ab, optimize=True)
    I2A_vooo = H.aa.vooo - np.einsum("me,aeij->amij", H.a.ov, T.aa, optimize=True)
    dA_aab, dB_aab, dC_aab, dD_aab = ccp3_opt_loops.ccp3_opt_loops.ccp3b_2ba(
            t3_excitations["aab"].T,
            T.aa, T.ab, L.a, L.b, L.aa, L.ab,
            I2B_ovoo, I2B_vooo, I2A_vooo,
            H.ab.vvvo, H.ab.vvov, H.aa.vvov,
            H.ab.vovv, H.ab.ovvv, H.aa.vovv,
            H.ab.ooov, H.ab.oovo, H.aa.ooov,
            H.a.ov, H.b.ov, H.aa.oovv, H.ab.oovv,
            H0.a.oo, H0.a.vv, H0.b.oo, H0.b.vv,
            H.a.oo, H.a.vv, H.b.oo, H.b.vv,
            H.aa.voov, H.aa.oooo, H.aa.vvvv, H.ab.ovov,
            H.ab.vovo, H.ab.oooo, H.ab.vvvv, H.bb.voov,
            d3aaa_o, d3aaa_v, d3aab_o, d3aab_v, d3abb_o, d3abb_v,
    )
    if use_RHF:
        correction_A = 2.0 * dA_aaa + 2.0 * dA_aab
        correction_B = 2.0 * dB_aaa + 2.0 * dB_aab
        correction_C = 2.0 * dC_aaa + 2.0 * dC_aab
        correction_D = 2.0 * dD_aaa + 2.0 * dD_aab
    else:
        I2B_vooo = H.ab.vooo - np.einsum("me,aeij->amij", H.b.ov, T.ab, optimize=True)
        I2C_vooo = H.bb.vooo - np.einsum("me,cekj->cmkj", H.b.ov, T.bb, optimize=True)
        I2B_ovoo = H.ab.ovoo - np.einsum("me,ebij->mbij", H.a.ov, T.ab, optimize=True)

        dA_abb, dB_abb, dC_abb, dD_abb = ccp3_opt_loops.ccp3_opt_loops.ccp3c_2ba(
                t3_excitations["abb"].T,
                T.ab, T.bb, L.a, L.b, L.ab, L.bb,
                I2B_vooo, I2C_vooo, I2B_ovoo,
                H.ab.vvov, H.bb.vvov, H.ab.vvvo, H.ab.ovvv,
                H.ab.vovv, H.bb.vovv, H.ab.oovo, H.ab.ooov,
                H.bb.ooov,
                H.a.ov, H.b.ov,
                H.ab.oovv, H.bb.oovv,
                H0.a.oo, H0.a.vv, H0.b.oo, H0.b.vv,
                H.a.oo, H.a.vv, H.b.oo, H.b.vv,
                H.aa.voov, H.ab.ovov, H.ab.vovo, H.ab.oooo,
                H.ab.vvvv, H.bb.voov, H.bb.oooo, H.bb.vvvv,
                d3aab_o, d3aab_v, d3abb_o, d3abb_v, d3bbb_o, d3bbb_v,
        )

        I2C_vvov = H.bb.vvov + np.einsum("me,abim->abie", H.b.ov, T.bb, optimize=True)
        dA_bbb, dB_bbb, dC_bbb, dD_bbb = ccp3_opt_loops.ccp3_opt_loops.ccp3d_2ba(
                t3_excitations["bbb"].T,
                T.bb, L.b, L.bb,
                H.bb.vooo, I2C_vvov, H.bb.oovv, H.b.ov,
                H.bb.vovv, H.bb.ooov, H0.b.oo, H0.b.vv,
                H.b.oo, H.b.vv, H.bb.voov, H.bb.oooo, H.bb.vvvv,
                d3bbb_o, d3bbb_v,
        )

        correction_A = dA_aaa + dA_aab + dA_abb + dA_bbb
        correction_B = dB_aaa + dB_aab + dB_abb + dB_bbb
        correction_C = dC_aaa + dC_aab + dC_abb + dC_bbb
        correction_D = dD_aaa + dD_aab + dD_abb + dD_bbb

    t_end = time.perf_counter()
    minutes, seconds = divmod(t_end - t_start, 60)

    energy_A = corr_energy + correction_A
    energy_B = corr_energy + correction_B
    energy_C = corr_energy + correction_C
    energy_D = corr_energy + correction_D

    total_energy_A = system.reference_energy + energy_A
    total_energy_B = system.reference_energy + energy_B
    total_energy_C = system.reference_energy + energy_C
    total_energy_D = system.reference_energy + energy_D

    print('   CC(P;3) Calculation Summary')
    print('   -------------------------------------')
    print("   Completed in  ({:0.2f}m  {:0.2f}s)\n".format(minutes, seconds))
    print("   CC(P) = {:>10.10f}".format(system.reference_energy + corr_energy))
    print(
        "   CC(P;3)_A = {:>10.10f}     ΔE_A = {:>10.10f}     δ_A = {:>10.10f}".format(
            total_energy_A, energy_A, correction_A
        )
    )
    print(
        "   CC(P;3)_B = {:>10.10f}     ΔE_B = {:>10.10f}     δ_B = {:>10.10f}".format(
            total_energy_B, energy_B, correction_B
        )
    )
    print(
        "   CC(P;3)_C = {:>10.10f}     ΔE_C = {:>10.10f}     δ_C = {:>10.10f}".format(
            total_energy_C, energy_C, correction_C
        )
    )
    print(
        "   CC(P;3)_D = {:>10.10f}     ΔE_D = {:>10.10f}     δ_D = {:>10.10f}\n".format(
            total_energy_D, energy_D, correction_D
        )
    )

    Eccp3 = {"A": total_energy_A, "B": total_energy_B, "C": total_energy_C, "D": total_energy_D}
    deltap3 = {"A": correction_A, "B": correction_B, "C": correction_C, "D": correction_D}

    return Eccp3, deltap3

# def calc_ccp3_with_moments(T, L, corr_energy, H, H0, system, pspace, use_RHF=False):
#     """
#     Calculate the ground-state CC(P;3) correction to the CC(P) energy and return the full moment arrays.
#     """
#     t_start = time.perf_counter()
#
#     # get the Hbar 3-body diagonal
#     d3aaa_v, d3aaa_o = aaa_H3_aaa_diagonal(T, H, system)
#     d3aab_v, d3aab_o = aab_H3_aab_diagonal(T, H, system)
#     d3abb_v, d3abb_o = abb_H3_abb_diagonal(T, H, system)
#     d3bbb_v, d3bbb_o = bbb_H3_bbb_diagonal(T, H, system)
#
#     moments = {"aaa" : [], "aab" : [], "abb" : [], "bbb" : []}
#
#     #### aaa correction ####
#     # calculate intermediates
#     I2A_vvov = H.aa.vvov + np.einsum("me,abim->abie", H.a.ov, T.aa, optimize=True)
#     # perform correction in-loop
#     dA_aaa, dB_aaa, dC_aaa, dD_aaa, moments["aaa"] = ccp3_adaptive_loops.ccp3_adaptive_loops.crcc23a_p_full_moment(
#             pspace['aaa'],
#             T.aa, L.a, L.aa,
#             H.aa.vooo, I2A_vvov, H0.aa.oovv, H.a.ov,
#             H.aa.vovv, H.aa.ooov, H0.a.oo, H0.a.vv,
#             H.a.oo, H.a.vv, H.aa.voov, H.aa.oooo,
#             H.aa.vvvv,
#             d3aaa_o, d3aaa_v,
#             system.noccupied_alpha, system.nunoccupied_alpha,
#     )
#
#     #### aab correction ####
#     # calculate intermediates
#     I2B_ovoo = H.ab.ovoo - np.einsum("me,ecjk->mcjk", H.a.ov, T.ab, optimize=True)
#     I2B_vooo = H.ab.vooo - np.einsum("me,aeik->amik", H.b.ov, T.ab, optimize=True)
#     I2A_vooo = H.aa.vooo - np.einsum("me,aeij->amij", H.a.ov, T.aa, optimize=True)
#
#     dA_aab, dB_aab, dC_aab, dD_aab, moments["aab"] = ccp3_adaptive_loops.ccp3_adaptive_loops.crcc23b_p_full_moment(
#             pspace['aab'],
#             T.aa, T.ab, L.a, L.b, L.aa, L.ab,
#             I2B_ovoo, I2B_vooo, I2A_vooo,
#             H.ab.vvvo, H.ab.vvov, H.aa.vvov,
#             H.ab.vovv, H.ab.ovvv, H.aa.vovv,
#             H.ab.ooov, H.ab.oovo, H.aa.ooov,
#             H.a.ov, H.b.ov, H0.aa.oovv, H0.ab.oovv,
#             H0.a.oo, H0.a.vv, H0.b.oo, H0.b.vv,
#             H.a.oo, H.a.vv, H.b.oo, H.b.vv,
#             H.aa.voov, H.aa.oooo, H.aa.vvvv, H.ab.ovov,
#             H.ab.vovo, H.ab.oooo, H.ab.vvvv, H.bb.voov,
#             d3aaa_o, d3aaa_v, d3aab_o, d3aab_v, d3abb_o, d3abb_v,
#             system.noccupied_alpha, system.nunoccupied_alpha,
#             system.noccupied_beta, system.nunoccupied_beta,
#     )
#
#     if use_RHF:
#         correction_A = 2.0 * dA_aaa + 2.0 * dA_aab
#         correction_B = 2.0 * dB_aaa + 2.0 * dB_aab
#         correction_C = 2.0 * dC_aaa + 2.0 * dC_aab
#         correction_D = 2.0 * dD_aaa + 2.0 * dD_aab
#     else:
#         I2B_vooo = H.ab.vooo - np.einsum("me,aeij->amij", H.b.ov, T.ab, optimize=True)
#         I2C_vooo = H.bb.vooo - np.einsum("me,cekj->cmkj", H.b.ov, T.bb, optimize=True)
#         I2B_ovoo = H.ab.ovoo - np.einsum("me,ebij->mbij", H.a.ov, T.ab, optimize=True)
#
#         dA_abb, dB_abb, dC_abb, dD_abb, moments["abb"] = ccp3_adaptive_loops.ccp3_adaptive_loops.crcc23c_p_full_moment(
#                 pspace['abb'],
#                 T.ab, T.bb, L.a, L.b, L.ab, L.bb,
#                 I2B_vooo, I2C_vooo, I2B_ovoo,
#                 H.ab.vvov, H.bb.vvov, H.ab.vvvo, H.ab.ovvv,
#                 H.ab.vovv, H.bb.vovv, H.ab.oovo, H.ab.ooov,
#                 H.bb.ooov,
#                 H.a.ov, H.b.ov,
#                 H0.ab.oovv, H0.bb.oovv,
#                 H0.a.oo, H0.a.vv, H0.b.oo, H0.b.vv,
#                 H.a.oo, H.a.vv, H.b.oo, H.b.vv,
#                 H.aa.voov, H.ab.ovov, H.ab.vovo, H.ab.oooo,
#                 H.ab.vvvv, H.bb.voov, H.bb.oooo, H.bb.vvvv,
#                 d3aab_o, d3aab_v, d3abb_o, d3abb_v, d3bbb_o, d3bbb_v,
#                 system.noccupied_alpha, system.nunoccupied_alpha,
#                 system.noccupied_beta, system.nunoccupied_beta,
#         )
#
#         I2C_vvov = H.bb.vvov + np.einsum("me,abim->abie", H.b.ov, T.bb, optimize=True)
#
#         dA_bbb, dB_bbb, dC_bbb, dD_bbb, moments["bbb"] = ccp3_adaptive_loops.ccp3_adaptive_loops.crcc23d_p_full_moment(
#                 pspace['bbb'],
#                 T.bb, L.b, L.bb,
#                 H.bb.vooo, I2C_vvov, H0.bb.oovv, H.b.ov,
#                 H.bb.vovv, H.bb.ooov, H0.b.oo, H0.b.vv,
#                 H.b.oo, H.b.vv, H.bb.voov, H.bb.oooo, H.bb.vvvv,
#                 d3bbb_o, d3bbb_v,
#                 system.noccupied_beta, system.nunoccupied_beta,
#         )
#
#         correction_A = dA_aaa + dA_aab + dA_abb + dA_bbb
#         correction_B = dB_aaa + dB_aab + dB_abb + dB_bbb
#         correction_C = dC_aaa + dC_aab + dC_abb + dC_bbb
#         correction_D = dD_aaa + dD_aab + dD_abb + dD_bbb
#
#     t_end = time.perf_counter()
#     minutes, seconds = divmod(t_end - t_start, 60)
#
#     # print the results
#     energy_A = corr_energy + correction_A
#     energy_B = corr_energy + correction_B
#     energy_C = corr_energy + correction_C
#     energy_D = corr_energy + correction_D
#
#     total_energy_A = system.reference_energy + energy_A
#     total_energy_B = system.reference_energy + energy_B
#     total_energy_C = system.reference_energy + energy_C
#     total_energy_D = system.reference_energy + energy_D
#
#     print('   CC(P;3) Calculation Summary')
#     print('   -------------------------------------')
#     print("   Completed in  ({:0.2f}m  {:0.2f}s)\n".format(minutes, seconds))
#     print("   CC(P) = {:>10.10f}".format(system.reference_energy + corr_energy))
#     print(
#         "   CC(P;3)_A = {:>10.10f}     ΔE_A = {:>10.10f}     δ_A = {:>10.10f}".format(
#             total_energy_A, energy_A, correction_A
#         )
#     )
#     print(
#         "   CC(P;3)_B = {:>10.10f}     ΔE_B = {:>10.10f}     δ_B = {:>10.10f}".format(
#             total_energy_B, energy_B, correction_B
#         )
#     )
#     print(
#         "   CC(P;3)_C = {:>10.10f}     ΔE_C = {:>10.10f}     δ_C = {:>10.10f}".format(
#             total_energy_C, energy_C, correction_C
#         )
#     )
#     print(
#         "   CC(P;3)_D = {:>10.10f}     ΔE_D = {:>10.10f}     δ_D = {:>10.10f}\n".format(
#             total_energy_D, energy_D, correction_D
#         )
#     )
#
#     Eccp3 = {"A": total_energy_A, "B": total_energy_B, "C": total_energy_C, "D": total_energy_D}
#     deltap3 = {"A": correction_A, "B": correction_B, "C": correction_C, "D": correction_D}
#
#     return Eccp3["D"], moments

# def calc_ccp3_with_selection(T, L, corr_energy, H, H0, system, pspace, num_add, use_RHF=False):
#     """
#     Calculate the ground-state CC(P;3) correction to the CC(P) energy.
#     """
#     t_start = time.perf_counter()
#
#     # get the Hbar 3-body diagonal
#     d3aaa_v, d3aaa_o = aaa_H3_aaa_diagonal(T, H, system)
#     d3aab_v, d3aab_o = aab_H3_aab_diagonal(T, H, system)
#     d3abb_v, d3abb_o = abb_H3_abb_diagonal(T, H, system)
#     d3bbb_v, d3bbb_o = bbb_H3_bbb_diagonal(T, H, system)
#
#     # initialize empty moments vector and triples list
#     num_add = int(num_add)
#     moments = np.zeros(num_add)
#     triples_list = np.zeros((num_add, 6), dtype=np.int8)
#
#     #### aaa correction ####
#     # calculate intermediates
#     I2A_vvov = H.aa.vvov + np.einsum("me,abim->abie", H.a.ov, T.aa, optimize=True)
#     # perform correction in-loop
#     dA_aaa, dB_aaa, dC_aaa, dD_aaa, moments, triples_list = ccp3_adaptive_loops.ccp3_adaptive_loops.crcc23a_p_with_selection(
#         moments,
#         triples_list,
#         pspace['aaa'],
#         T.aa, L.a, L.aa,
#         H.aa.vooo, I2A_vvov, H0.aa.oovv, H.a.ov,
#         H.aa.vovv, H.aa.ooov, H0.a.oo, H0.a.vv,
#         H.a.oo, H.a.vv, H.aa.voov, H.aa.oooo,
#         H.aa.vvvv,
#         d3aaa_o, d3aaa_v,
#         system.noccupied_alpha, system.nunoccupied_alpha, num_add,
#         )
#
#     #### aab correction ####
#     # calculate intermediates
#     I2B_ovoo = H.ab.ovoo - np.einsum("me,ecjk->mcjk", H.a.ov, T.ab, optimize=True)
#     I2B_vooo = H.ab.vooo - np.einsum("me,aeik->amik", H.b.ov, T.ab, optimize=True)
#     I2A_vooo = H.aa.vooo - np.einsum("me,aeij->amij", H.a.ov, T.aa, optimize=True)
#     dA_aab, dB_aab, dC_aab, dD_aab, moments, triples_list = ccp3_adaptive_loops.ccp3_adaptive_loops.crcc23b_p_with_selection(
#         moments,
#         triples_list,
#         pspace['aab'],
#         T.aa, T.ab, L.a, L.b, L.aa, L.ab,
#         I2B_ovoo, I2B_vooo, I2A_vooo,
#         H.ab.vvvo, H.ab.vvov, H.aa.vvov,
#         H.ab.vovv, H.ab.ovvv, H.aa.vovv,
#         H.ab.ooov, H.ab.oovo, H.aa.ooov,
#         H.a.ov, H.b.ov, H0.aa.oovv, H0.ab.oovv,
#         H0.a.oo, H0.a.vv, H0.b.oo, H0.b.vv,
#         H.a.oo, H.a.vv, H.b.oo, H.b.vv,
#         H.aa.voov, H.aa.oooo, H.aa.vvvv, H.ab.ovov,
#         H.ab.vovo, H.ab.oooo, H.ab.vvvv, H.bb.voov,
#         d3aaa_o, d3aaa_v, d3aab_o, d3aab_v, d3abb_o, d3abb_v,
#         system.noccupied_alpha, system.nunoccupied_alpha,
#         system.noccupied_beta, system.nunoccupied_beta,
#         num_add,
#     )
#
#     if use_RHF:
#         correction_A = 2.0 * dA_aaa + 2.0 * dA_aab
#         correction_B = 2.0 * dB_aaa + 2.0 * dB_aab
#         correction_C = 2.0 * dC_aaa + 2.0 * dC_aab
#         correction_D = 2.0 * dD_aaa + 2.0 * dD_aab
#     else:
#         I2B_vooo = H.ab.vooo - np.einsum("me,aeij->amij", H.b.ov, T.ab, optimize=True)
#         I2C_vooo = H.bb.vooo - np.einsum("me,cekj->cmkj", H.b.ov, T.bb, optimize=True)
#         I2B_ovoo = H.ab.ovoo - np.einsum("me,ebij->mbij", H.a.ov, T.ab, optimize=True)
#         dA_abb, dB_abb, dC_abb, dD_abb, moments, triples_list = ccp3_adaptive_loops.ccp3_adaptive_loops.crcc23c_p_with_selection(
#             moments,
#             triples_list,
#             pspace['abb'],
#             T.ab, T.bb, L.a, L.b, L.ab, L.bb,
#             I2B_vooo, I2C_vooo, I2B_ovoo,
#             H.ab.vvov, H.bb.vvov, H.ab.vvvo, H.ab.ovvv,
#             H.ab.vovv, H.bb.vovv, H.ab.oovo, H.ab.ooov,
#             H.bb.ooov,
#             H.a.ov, H.b.ov,
#             H0.ab.oovv, H0.bb.oovv,
#             H0.a.oo, H0.a.vv, H0.b.oo, H0.b.vv,
#             H.a.oo, H.a.vv, H.b.oo, H.b.vv,
#             H.aa.voov, H.ab.ovov, H.ab.vovo, H.ab.oooo,
#             H.ab.vvvv, H.bb.voov, H.bb.oooo, H.bb.vvvv,
#             d3aab_o, d3aab_v, d3abb_o, d3abb_v, d3bbb_o, d3bbb_v,
#             system.noccupied_alpha, system.nunoccupied_alpha,
#             system.noccupied_beta, system.nunoccupied_beta,
#             num_add,
#         )
#
#         I2C_vvov = H.bb.vvov + np.einsum("me,abim->abie", H.b.ov, T.bb, optimize=True)
#         dA_bbb, dB_bbb, dC_bbb, dD_bbb, moments, triples_list = ccp3_adaptive_loops.ccp3_adaptive_loops.crcc23d_p_with_selection(
#             moments,
#             triples_list,
#             pspace['bbb'],
#             T.bb, L.b, L.bb,
#             H.bb.vooo, I2C_vvov, H0.bb.oovv, H.b.ov,
#             H.bb.vovv, H.bb.ooov, H0.b.oo, H0.b.vv,
#             H.b.oo, H.b.vv, H.bb.voov, H.bb.oooo, H.bb.vvvv,
#             d3bbb_o, d3bbb_v,
#             system.noccupied_beta, system.nunoccupied_beta, num_add,
#         )
#
#
#         correction_A = dA_aaa + dA_aab + dA_abb + dA_bbb
#         correction_B = dB_aaa + dB_aab + dB_abb + dB_bbb
#         correction_C = dC_aaa + dC_aab + dC_abb + dC_bbb
#         correction_D = dD_aaa + dD_aab + dD_abb + dD_bbb
#
#     t_end = time.perf_counter()
#     minutes, seconds = divmod(t_end - t_start, 60)
#
#     # print the results
#     energy_A = corr_energy + correction_A
#     energy_B = corr_energy + correction_B
#     energy_C = corr_energy + correction_C
#     energy_D = corr_energy + correction_D
#
#     total_energy_A = system.reference_energy + energy_A
#     total_energy_B = system.reference_energy + energy_B
#     total_energy_C = system.reference_energy + energy_C
#     total_energy_D = system.reference_energy + energy_D
#
#     print('   CC(P;3) Calculation Summary')
#     print('   -------------------------------------')
#     print("   Completed in  ({:0.2f}m  {:0.2f}s)\n".format(minutes, seconds))
#     print("   CC(P) = {:>10.10f}".format(system.reference_energy + corr_energy))
#     print(
#         "   CC(P;3)_A = {:>10.10f}     ΔE_A = {:>10.10f}     δ_A = {:>10.10f}".format(
#             total_energy_A, energy_A, correction_A
#         )
#     )
#     print(
#         "   CC(P;3)_B = {:>10.10f}     ΔE_B = {:>10.10f}     δ_B = {:>10.10f}".format(
#             total_energy_B, energy_B, correction_B
#         )
#     )
#     print(
#         "   CC(P;3)_C = {:>10.10f}     ΔE_C = {:>10.10f}     δ_C = {:>10.10f}".format(
#             total_energy_C, energy_C, correction_C
#         )
#     )
#     print(
#         "   CC(P;3)_D = {:>10.10f}     ΔE_D = {:>10.10f}     δ_D = {:>10.10f}\n".format(
#             total_energy_D, energy_D, correction_D
#         )
#     )
#     print(
#         "   Selected moments account for {:>5.2f}% of the total CC(P;3)_D correction\n".format(
#             sum(moments) / correction_D * 100
#         )
#     )
#
#     Eccp3 = {"A": total_energy_A, "B": total_energy_B, "C": total_energy_C, "D": total_energy_D}
#     deltap3 = {"A": correction_A, "B": correction_B, "C": correction_C, "D": correction_D}
#
#     return Eccp3["D"], triples_list

def calc_ccp3_with_selection(T, L, t3_excitations, corr_energy, H, H0, system, num_add, use_RHF=False, min_thresh=0.0):
    """
    Calculate the ground-state CC(P;3) correction to the CC(P) energy.
    """
    t_start = time.perf_counter()

    # get the Hbar 3-body diagonal
    d3aaa_v, d3aaa_o = aaa_H3_aaa_diagonal(T, H, system)
    d3aab_v, d3aab_o = aab_H3_aab_diagonal(T, H, system)
    d3abb_v, d3abb_o = abb_H3_abb_diagonal(T, H, system)
    d3bbb_v, d3bbb_o = bbb_H3_bbb_diagonal(T, H, system)

    # initialize empty moments vector and triples list
    num_add = int(num_add)
    moments = np.zeros(2 * num_add)
    triples_list = np.zeros((2 * num_add, 6), dtype=np.int32)

    #### aaa correction ####
    # calculate intermediates
    I2A_vvov = H.aa.vvov + np.einsum("me,abim->abie", H.a.ov, T.aa, optimize=True)
    # perform correction in-loop
    nfill = 1
    dA_aaa, dB_aaa, dC_aaa, dD_aaa, moments, triples_list, nfill = ccp3_adaptive_loops.ccp3_adaptive_loops.ccp3a_2ba_with_selection_opt(
        moments,
        triples_list,
        nfill,
        t3_excitations['aaa'].T,
        T.aa, L.a, L.aa,
        H.aa.vooo, I2A_vvov, H0.aa.oovv, H.a.ov,
        H.aa.vovv, H.aa.ooov, H0.a.oo, H0.a.vv,
        H.a.oo, H.a.vv, H.aa.voov, H.aa.oooo,
        H.aa.vvvv,
        d3aaa_o, d3aaa_v,
        min_thresh,
        )

    #### aab correction ####
    # calculate intermediates
    I2B_ovoo = H.ab.ovoo - np.einsum("me,ecjk->mcjk", H.a.ov, T.ab, optimize=True)
    I2B_vooo = H.ab.vooo - np.einsum("me,aeik->amik", H.b.ov, T.ab, optimize=True)
    I2A_vooo = H.aa.vooo - np.einsum("me,aeij->amij", H.a.ov, T.aa, optimize=True)
    dA_aab, dB_aab, dC_aab, dD_aab, moments, triples_list, nfill = ccp3_adaptive_loops.ccp3_adaptive_loops.ccp3b_2ba_with_selection_opt(
        moments,
        triples_list,
        nfill,
        t3_excitations['aab'].T,
        T.aa, T.ab, L.a, L.b, L.aa, L.ab,
        I2B_ovoo, I2B_vooo, I2A_vooo,
        H.ab.vvvo, H.ab.vvov, H.aa.vvov,
        H.ab.vovv, H.ab.ovvv, H.aa.vovv,
        H.ab.ooov, H.ab.oovo, H.aa.ooov,
        H.a.ov, H.b.ov, H0.aa.oovv, H0.ab.oovv,
        H0.a.oo, H0.a.vv, H0.b.oo, H0.b.vv,
        H.a.oo, H.a.vv, H.b.oo, H.b.vv,
        H.aa.voov, H.aa.oooo, H.aa.vvvv, H.ab.ovov,
        H.ab.vovo, H.ab.oooo, H.ab.vvvv, H.bb.voov,
        d3aaa_o, d3aaa_v, d3aab_o, d3aab_v, d3abb_o, d3abb_v,
        min_thresh,
    )

    if use_RHF:
        correction_A = 2.0 * dA_aaa + 2.0 * dA_aab
        correction_B = 2.0 * dB_aaa + 2.0 * dB_aab
        correction_C = 2.0 * dC_aaa + 2.0 * dC_aab
        correction_D = 2.0 * dD_aaa + 2.0 * dD_aab
    else:
        I2B_vooo = H.ab.vooo - np.einsum("me,aeij->amij", H.b.ov, T.ab, optimize=True)
        I2C_vooo = H.bb.vooo - np.einsum("me,cekj->cmkj", H.b.ov, T.bb, optimize=True)
        I2B_ovoo = H.ab.ovoo - np.einsum("me,ebij->mbij", H.a.ov, T.ab, optimize=True)
        dA_abb, dB_abb, dC_abb, dD_abb, moments, triples_list, nfill = ccp3_adaptive_loops.ccp3_adaptive_loops.ccp3c_2ba_with_selection_opt(
            moments,
            triples_list,
            nfill,
            t3_excitations['abb'].T,
            T.ab, T.bb, L.a, L.b, L.ab, L.bb,
            I2B_vooo, I2C_vooo, I2B_ovoo,
            H.ab.vvov, H.bb.vvov, H.ab.vvvo, H.ab.ovvv,
            H.ab.vovv, H.bb.vovv, H.ab.oovo, H.ab.ooov,
            H.bb.ooov,
            H.a.ov, H.b.ov,
            H0.ab.oovv, H0.bb.oovv,
            H0.a.oo, H0.a.vv, H0.b.oo, H0.b.vv,
            H.a.oo, H.a.vv, H.b.oo, H.b.vv,
            H.aa.voov, H.ab.ovov, H.ab.vovo, H.ab.oooo,
            H.ab.vvvv, H.bb.voov, H.bb.oooo, H.bb.vvvv,
            d3aab_o, d3aab_v, d3abb_o, d3abb_v, d3bbb_o, d3bbb_v,
            min_thresh,
        )

        I2C_vvov = H.bb.vvov + np.einsum("me,abim->abie", H.b.ov, T.bb, optimize=True)
        dA_bbb, dB_bbb, dC_bbb, dD_bbb, moments, triples_list, nfill = ccp3_adaptive_loops.ccp3_adaptive_loops.ccp3d_2ba_with_selection_opt(
            moments,
            triples_list,
            nfill,
            t3_excitations['bbb'].T,
            T.bb, L.b, L.bb,
            H.bb.vooo, I2C_vvov, H0.bb.oovv, H.b.ov,
            H.bb.vovv, H.bb.ooov, H0.b.oo, H0.b.vv,
            H.b.oo, H.b.vv, H.bb.voov, H.bb.oooo, H.bb.vvvv,
            d3bbb_o, d3bbb_v,
            min_thresh,
        )

        correction_A = dA_aaa + dA_aab + dA_abb + dA_bbb
        correction_B = dB_aaa + dB_aab + dB_abb + dB_bbb
        correction_C = dC_aaa + dC_aab + dC_abb + dC_bbb
        correction_D = dD_aaa + dD_aab + dD_abb + dD_bbb

    # Important: perform a final sort of the excitations and moments, returning the first half only
    idx = np.argsort(np.abs(moments))
    triples_list = triples_list[idx[::-1], :]
    triples_list = triples_list[:len(idx) // 2, :]

    t_end = time.perf_counter()
    minutes, seconds = divmod(t_end - t_start, 60)

    # print the results
    energy_A = corr_energy + correction_A
    energy_B = corr_energy + correction_B
    energy_C = corr_energy + correction_C
    energy_D = corr_energy + correction_D

    total_energy_A = system.reference_energy + energy_A
    total_energy_B = system.reference_energy + energy_B
    total_energy_C = system.reference_energy + energy_C
    total_energy_D = system.reference_energy + energy_D

    print('   CC(P;3) Calculation Summary')
    print('   ---------------------------')
    print("   Completed in  ({:0.2f}m  {:0.2f}s)\n".format(minutes, seconds))
    print("   CC(P) = {:>10.10f}".format(system.reference_energy + corr_energy))
    print(
        "   CC(P;3)_A = {:>10.10f}     ΔE_A = {:>10.10f}     δ_A = {:>10.10f}".format(
            total_energy_A, energy_A, correction_A
        )
    )
    print(
        "   CC(P;3)_B = {:>10.10f}     ΔE_B = {:>10.10f}     δ_B = {:>10.10f}".format(
            total_energy_B, energy_B, correction_B
        )
    )
    print(
        "   CC(P;3)_C = {:>10.10f}     ΔE_C = {:>10.10f}     δ_C = {:>10.10f}".format(
            total_energy_C, energy_C, correction_C
        )
    )
    print(
        "   CC(P;3)_D = {:>10.10f}     ΔE_D = {:>10.10f}     δ_D = {:>10.10f}\n".format(
            total_energy_D, energy_D, correction_D
        )
    )
    print(
        "   Selected moments account for {:>5.2f}% of the total CC(P;3)_D correction\n".format(
            sum(moments) / correction_D * 100
        )
    )

    Eccp3 = {"A": total_energy_A, "B": total_energy_B, "C": total_energy_C, "D": total_energy_D}
    deltap3 = {"A": correction_A, "B": correction_B, "C": correction_C, "D": correction_D}

    return Eccp3["D"], triples_list

# def calc_ccpert3(T, corr_energy, H, system, pspace, use_RHF=False):
#     """
#     Calculate the ground-state CC(P;Q)_(T) correction to the CC(P) energy associated
#     with the P space `pspace`.
#     """
#     t_start = time.perf_counter()
#
#     #### aaa correction ####
#     dA_aaa = ccsdpt_loops.ccsdpt_loops.ccsdpta_p(
#         pspace["aaa"],
#         T.a, T.aa,
#         H.aa.vooo, H.aa.vvov, H.aa.oovv, H.a.ov,
#         H.aa.vovv, H.aa.ooov,
#         H.a.oo, H.a.vv,
#         system.noccupied_alpha, system.nunoccupied_alpha,
#     )
#     #### aab correction ####
#     dA_aab = ccsdpt_loops.ccsdpt_loops.ccsdptb_p(
#         pspace["aab"],
#         T.a, T.b, T.aa, T.ab,
#         H.ab.ovoo, H.ab.vooo, H.aa.vooo,
#         H.ab.vvvo, H.ab.vvov, H.aa.vvov,
#         H.ab.vovv, H.ab.ovvv, H.aa.vovv,
#         H.ab.ooov, H.ab.oovo, H.aa.ooov,
#         H.a.ov, H.b.ov, H.aa.oovv, H.ab.oovv,
#         H.a.oo, H.a.vv, H.b.oo, H.b.vv,
#         system.noccupied_alpha, system.nunoccupied_alpha,
#         system.noccupied_beta, system.nunoccupied_beta,
#     )
#     # If using RHF, can terminate now
#     if use_RHF:
#         # Sum corrections for each spin case, using that aaa=bbb and aab=abb for RHF symmetry
#         correction_A = 2.0 * dA_aaa + 2.0 * dA_aab
#     else:
#         ### abb correction ###
#         dA_abb = ccsdpt_loops.ccsdpt_loops.ccsdptc_p(
#             pspace["abb"],
#             T.a, T.b, T.ab, T.bb,
#             H.ab.vooo, H.bb.vooo, H.ab.ovoo,
#             H.ab.vvov, H.bb.vvov, H.ab.vvvo, H.ab.ovvv,
#             H.ab.vovv, H.bb.vovv, H.ab.oovo, H.ab.ooov,
#             H.bb.ooov,
#             H.a.ov, H.b.ov,
#             H.ab.oovv, H.bb.oovv,
#             H.a.oo, H.a.vv, H.b.oo, H.b.vv,
#             system.noccupied_alpha, system.nunoccupied_alpha,
#             system.noccupied_beta, system.nunoccupied_beta,
#         )
#         ### bbb correction ###
#         dA_bbb = ccsdpt_loops.ccsdpt_loops.ccsdptd_p(
#             pspace["bbb"],
#             T.b, T.bb,
#             H.bb.vooo, H.bb.vvov, H.bb.oovv, H.b.ov,
#             H.bb.vovv, H.bb.ooov,
#             H.b.oo, H.b.vv,
#             system.noccupied_beta, system.nunoccupied_beta,
#         )
#         # Sum the corrections from each spincase
#         correction_A = dA_aaa + dA_aab + dA_abb + dA_bbb
#
#     t_end = time.perf_counter()
#     minutes, seconds = divmod(t_end - t_start, 60)
#
#     # print the results
#     energy_A = corr_energy + correction_A
#     total_energy_A = system.reference_energy + energy_A
#     Eccp3 = {"A" : total_energy_A}
#     deltap3 = {"A" : correction_A}
#
#     print('   CC(P;3)_(T) Calculation Summary')
#     print('   -------------------------------------')
#     print("   Completed in  ({:0.2f}m  {:0.2f}s)".format(minutes, seconds))
#     print("   CC(P) = {:>10.10f}".format(system.reference_energy + corr_energy))
#     print(
#         "   CC(P;3)_(T) = {:>10.10f}     ΔE_A = {:>10.10f}     δ_A = {:>10.10f}".format(
#             total_energy_A, energy_A, correction_A
#         )
#     )
#
#     return Eccp3, deltap3


# def calc_ccpert3_with_selection(T, corr_energy, H, system, pspace, num_add, use_RHF=False):
#     """
#     Calculate the ground-state CCSD(T) correction to the CC(P) energy.
#     """
#     t_start = time.perf_counter()
#
#     # initialize empty moments vector and triples list
#     num_add = int(num_add)
#     moments = np.zeros(num_add)
#     triples_list = np.zeros((num_add, 6), dtype=np.int8)
#
#     #### aaa correction ####
#     # calculate intermediates
#     #I2A_vvov = H.aa.vvov + np.einsum("me,abim->abie", H.a.ov, T.aa, optimize=True)
#     # perform correction in-loop
#     dA_aaa, moments, triples_list = ccsdpt_loops.ccsdpt_loops.ccsdpta_p_with_selection(
#         moments,
#         triples_list,
#         pspace["aaa"],
#         T.a, T.aa,
#         H.aa.vooo, H.aa.vvov, H.aa.oovv, H.a.ov,
#         H.aa.vovv, H.aa.ooov,
#         H.a.oo, H.a.vv,
#         system.noccupied_alpha, system.nunoccupied_alpha, num_add,
#     )
#     #### aab correction ####
#     # calculate intermediates
#     #I2B_ovoo = H.ab.ovoo - np.einsum("me,ecjk->mcjk", H.a.ov, T.ab, optimize=True)
#     #I2B_vooo = H.ab.vooo - np.einsum("me,aeik->amik", H.b.ov, T.ab, optimize=True)
#     #I2A_vooo = H.aa.vooo - np.einsum("me,aeij->amij", H.a.ov, T.aa, optimize=True)
#     dA_aab, moments, triples_list = ccsdpt_loops.ccsdpt_loops.ccsdptb_p_with_selection(
#         moments,
#         triples_list,
#         pspace["aab"],
#         T.a, T.b, T.aa, T.ab,
#         H.ab.ovoo, H.ab.vooo, H.aa.vooo,
#         H.ab.vvvo, H.ab.vvov, H.aa.vvov,
#         H.ab.vovv, H.ab.ovvv, H.aa.vovv,
#         H.ab.ooov, H.ab.oovo, H.aa.ooov,
#         H.a.ov, H.b.ov, H.aa.oovv, H.ab.oovv,
#         H.a.oo, H.a.vv, H.b.oo, H.b.vv,
#         system.noccupied_alpha, system.nunoccupied_alpha,
#         system.noccupied_beta, system.nunoccupied_beta,
#         num_add,
#     )
#
#     if use_RHF:
#         correction_A = 2.0 * dA_aaa + 2.0 * dA_aab
#     else:
#         #### abb correction ####
#         # calculate intermediates
#         #I2B_vooo = H.ab.vooo - np.einsum("me,aeij->amij", H.b.ov, T.ab, optimize=True)
#         #I2C_vooo = H.bb.vooo - np.einsum("me,cekj->cmkj", H.b.ov, T.bb, optimize=True)
#         #I2B_ovoo = H.ab.ovoo - np.einsum("me,ebij->mbij", H.a.ov, T.ab, optimize=True)
#         dA_abb, moments, triples_list = ccsdpt_loops.ccsdpt_loops.ccsdptc_p_with_selection(
#             moments,
#             triples_list,
#             pspace["abb"],
#             T.a, T.b, T.ab, T.bb,
#             H.ab.vooo, H.bb.vooo, H.ab.ovoo,
#             H.ab.vvov, H.bb.vvov, H.ab.vvvo, H.ab.ovvv,
#             H.ab.vovv, H.bb.vovv, H.ab.oovo, H.ab.ooov,
#             H.bb.ooov,
#             H.a.ov, H.b.ov,
#             H.ab.oovv, H.bb.oovv,
#             H.a.oo, H.a.vv, H.b.oo, H.b.vv,
#             system.noccupied_alpha, system.nunoccupied_alpha,
#             system.noccupied_beta, system.nunoccupied_beta,
#             num_add,
#         )
#
#         #### bbb correction ####
#         # calculate intermediates
#         #I2C_vvov = H.bb.vvov + np.einsum("me,abim->abie", H.b.ov, T.bb, optimize=True)
#         dA_bbb, moments, triples_list = ccsdpt_loops.ccsdpt_loops.ccsdptd_p_with_selection(
#             moments,
#             triples_list,
#             pspace["bbb"],
#             T.b, T.bb,
#             H.bb.vooo, H.bb.vvov, H.bb.oovv, H.b.ov,
#             H.bb.vovv, H.bb.ooov,
#             H.b.oo, H.b.vv,
#             system.noccupied_beta, system.nunoccupied_beta, num_add,
#         )
#
#         correction_A = dA_aaa + dA_aab + dA_abb + dA_bbb
#
#     t_end = time.perf_counter()
#     minutes, seconds = divmod(t_end - t_start, 60)
#
#     # print the results
#     energy_A = corr_energy + correction_A
#     total_energy_A = system.reference_energy + energy_A
#
#     print('   CC(P;3)_(T) Calculation Summary')
#     print('   -------------------------------------')
#     print("   Completed in  ({:0.2f}m  {:0.2f}s)".format(minutes, seconds))
#     print("   CC(P) = {:>10.10f}".format(system.reference_energy + corr_energy))
#     print(
#         "   CC(P;3)_(T) = {:>10.10f}     ΔE_A = {:>10.10f}     δ_A = {:>10.10f}".format(
#             total_energy_A, energy_A, correction_A
#         )
#     )
#     print(
#         "   Selected moments account for {:>5.2f}% of the total CC(P;3)_(T) correction\n".format(
#             sum(moments) / correction_A * 100
#         )
#     )
#
#     return total_energy_A, triples_list

# def calc_ccpert3_with_moments(T, corr_energy, H, system, pspace, use_RHF=False):
#     """
#     Calculate the ground-state CCSD(T) correction to the CC(P) energy using full moment arrays in memory.
#     """
#
#     moments = {"aaa": [], "aab": [], "abb": [], "bbb": []}
#
#     t_start = time.perf_counter()
#
#     #### aaa correction ####
#     # calculate intermediates
#     #I2A_vvov = H.aa.vvov + np.einsum("me,abim->abie", H.a.ov, T.aa, optimize=True)
#     # perform correction in-loop
#     dA_aaa, moments["aaa"] = ccsdpt_loops.ccsdpt_loops.ccsdpta_p_full_moment(
#         pspace["aaa"],
#         T.a, T.aa,
#         H.aa.vooo, H.aa.vvov, H.aa.oovv, H.a.ov,
#         H.aa.vovv, H.aa.ooov,
#         H.a.oo, H.a.vv,
#         system.noccupied_alpha, system.nunoccupied_alpha
#     )
#
#     #### aab correction ####
#     # calculate intermediates
#     #I2B_ovoo = H.ab.ovoo - np.einsum("me,ecjk->mcjk", H.a.ov, T.ab, optimize=True)
#     #I2B_vooo = H.ab.vooo - np.einsum("me,aeik->amik", H.b.ov, T.ab, optimize=True)
#     #I2A_vooo = H.aa.vooo - np.einsum("me,aeij->amij", H.a.ov, T.aa, optimize=True)
#     dA_aab, moments["aab"] = ccsdpt_loops.ccsdpt_loops.ccsdptb_p_full_moment(
#         pspace["aab"],
#         T.a, T.b, T.aa, T.ab,
#         H.ab.ovoo, H.ab.vooo, H.aa.vooo,
#         H.ab.vvvo, H.ab.vvov, H.aa.vvov,
#         H.ab.vovv, H.ab.ovvv, H.aa.vovv,
#         H.ab.ooov, H.ab.oovo, H.aa.ooov,
#         H.a.ov, H.b.ov, H.aa.oovv, H.ab.oovv,
#         H.a.oo, H.a.vv, H.b.oo, H.b.vv,
#         system.noccupied_alpha, system.nunoccupied_alpha,
#         system.noccupied_beta, system.nunoccupied_beta,
#     )
#
#     if use_RHF:
#         correction_A = 2.0 * dA_aaa + 2.0 * dA_aab
#     else:
#         #### abb correction ####
#         # calculate intermediates
#         #I2B_vooo = H.ab.vooo - np.einsum("me,aeij->amij", H.b.ov, T.ab, optimize=True)
#         #I2C_vooo = H.bb.vooo - np.einsum("me,cekj->cmkj", H.b.ov, T.bb, optimize=True)
#         #I2B_ovoo = H.ab.ovoo - np.einsum("me,ebij->mbij", H.a.ov, T.ab, optimize=True)
#         dA_abb, moments["abb"] = ccsdpt_loops.ccsdpt_loops.ccsdptc_p_full_moment(
#             pspace["abb"],
#             T.a, T.b, T.ab, T.bb,
#             H.ab.vooo, H.bb.vooo, H.ab.ovoo,
#             H.ab.vvov, H.bb.vvov, H.ab.vvvo, H.ab.ovvv,
#             H.ab.vovv, H.bb.vovv, H.ab.oovo, H.ab.ooov,
#             H.bb.ooov,
#             H.a.ov, H.b.ov,
#             H.ab.oovv, H.bb.oovv,
#             H.a.oo, H.a.vv, H.b.oo, H.b.vv,
#             system.noccupied_alpha, system.nunoccupied_alpha,
#             system.noccupied_beta, system.nunoccupied_beta,
#         )
#
#         #### bbb correction ####
#         # calculate intermediates
#         #I2C_vvov = H.bb.vvov + np.einsum("me,abim->abie", H.b.ov, T.bb, optimize=True)
#         dA_bbb, moments["bbb"] = ccsdpt_loops.ccsdpt_loops.ccsdptd_p_full_moment(
#             pspace["bbb"],
#             T.b, T.bb,
#             H.bb.vooo, H.bb.vvov, H.bb.oovv, H.b.ov,
#             H.bb.vovv, H.bb.ooov,
#             H.b.oo, H.b.vv,
#             system.noccupied_beta, system.nunoccupied_beta
#         )
#
#         correction_A = dA_aaa + dA_aab + dA_abb + dA_bbb
#
#     t_end = time.perf_counter()
#     minutes, seconds = divmod(t_end - t_start, 60)
#
#     # print the results
#     energy_A = corr_energy + correction_A
#     total_energy_A = system.reference_energy + energy_A
#
#     print('   CC(P;3)_(T) Calculation Summary')
#     print('   -------------------------------------')
#     print("   Completed in  ({:0.2f}m  {:0.2f}s)".format(minutes, seconds))
#     print("   CC(P) = {:>10.10f}".format(system.reference_energy + corr_energy))
#     print(
#         "   CC(P;3)_(T) = {:>10.10f}     ΔE_A = {:>10.10f}     δ_A = {:>10.10f}".format(
#             total_energy_A, energy_A, correction_A
#         )
#     )
#     return total_energy_A, moments


def build_M3A_full(T, H, H0):
    """
    Update t3a amplitudes by calculating the projection <ijkabc|(H_N e^(T1+T2+T3))_C|0>.
    """

    # <ijkabc | H(2) | 0 > + (VT3)_C intermediates
    # Recall that we are using HBar CCSDT, so the vooo and vvov parts have T3 in it already!
    I2A_vvov = H.aa.vvov + np.einsum("me,abim->abie", H.a.ov, T.aa, optimize=True)

    # MM(2,3)A
    MM23A = -0.25 * np.einsum("amij,bcmk->abcijk", H.aa.vooo, T.aa, optimize=True)
    MM23A += 0.25 * np.einsum("abie,ecjk->abcijk", I2A_vvov, T.aa, optimize=True)
    # (HBar*T3)_C
    MM23A -= (1.0 / 12.0) * np.einsum("mk,abcijm->abcijk", H.a.oo, T.aaa, optimize=True)
    MM23A += (1.0 / 12.0) * np.einsum("ce,abeijk->abcijk", H.a.vv, T.aaa, optimize=True)
    MM23A += (1.0 / 24.0) * np.einsum("mnij,abcmnk->abcijk", H.aa.oooo, T.aaa, optimize=True)
    MM23A += (1.0 / 24.0) * np.einsum("abef,efcijk->abcijk", H.aa.vvvv, T.aaa, optimize=True)
    MM23A += 0.25 * np.einsum("cmke,abeijm->abcijk", H.aa.voov, T.aaa, optimize=True)
    MM23A += 0.25 * np.einsum("cmke,abeijm->abcijk", H.ab.voov, T.aab, optimize=True)

    MM23A -= np.transpose(MM23A, (0, 1, 2, 3, 5, 4)) # (jk)
    MM23A -= np.transpose(MM23A, (0, 1, 2, 4, 3, 5)) + np.transpose(MM23A, (0, 1, 2, 5, 4, 3)) # (i/jk)
    MM23A -= np.transpose(MM23A, (0, 2, 1, 3, 4, 5)) # (bc)
    MM23A -= np.transpose(MM23A, (2, 1, 0, 3, 4, 5)) + np.transpose(MM23A, (1, 0, 2, 3, 4, 5)) # (a/bc)

    return MM23A


# @profile
def build_M3B_full(T, H, H0):
    """
    Update t3b amplitudes by calculating the projection <ijk~abc~|(H_N e^(T1+T2+T3))_C|0>.
    """
    # <ijk~abc~ | H(2) | 0 > + (VT3)_C intermediates
    # Recall that we are using HBar CCSDT, so the vooo and vvov parts have T3 in it already!
    I2A_vooo = H.aa.vooo - np.einsum("me,aeij->amij", H.a.ov, T.aa, optimize=True)
    I2B_ovoo = H.ab.ovoo - np.einsum("me,ecjk->mcjk", H.a.ov, T.ab, optimize=True)
    I2B_vooo = H.ab.vooo - np.einsum("me,aeik->amik", H.b.ov, T.ab, optimize=True)

    # MM(2,3)B
    MM23B = 0.5 * np.einsum("bcek,aeij->abcijk", H.ab.vvvo, T.aa, optimize=True)
    MM23B -= 0.5 * np.einsum("mcjk,abim->abcijk", I2B_ovoo, T.aa, optimize=True)
    MM23B += np.einsum("acie,bejk->abcijk", H.ab.vvov, T.ab, optimize=True)
    MM23B -= np.einsum("amik,bcjm->abcijk", I2B_vooo, T.ab, optimize=True)
    MM23B += 0.5 * np.einsum("abie,ecjk->abcijk", H.aa.vvov, T.ab, optimize=True)
    MM23B -= 0.5 * np.einsum("amij,bcmk->abcijk", I2A_vooo, T.ab, optimize=True)
    # (HBar*T3)_C
    MM23B -= 0.5 * np.einsum("mi,abcmjk->abcijk", H.a.oo, T.aab, optimize=True)
    MM23B -= 0.25 * np.einsum("mk,abcijm->abcijk", H.b.oo, T.aab, optimize=True)
    MM23B += 0.5 * np.einsum("ae,ebcijk->abcijk", H.a.vv, T.aab, optimize=True)
    MM23B += 0.25 * np.einsum("ce,abeijk->abcijk", H.b.vv, T.aab, optimize=True)
    MM23B += 0.125 * np.einsum("mnij,abcmnk->abcijk", H.aa.oooo, T.aab, optimize=True)
    MM23B += 0.5 * np.einsum("mnjk,abcimn->abcijk", H.ab.oooo, T.aab, optimize=True)
    MM23B += 0.125 * np.einsum("abef,efcijk->abcijk", H.aa.vvvv, T.aab, optimize=True)
    MM23B += 0.5 * np.einsum("bcef,aefijk->abcijk", H.ab.vvvv, T.aab, optimize=True)
    MM23B += np.einsum("amie,ebcmjk->abcijk", H.aa.voov, T.aab, optimize=True)
    MM23B += np.einsum("amie,becjmk->abcijk", H.ab.voov, T.abb, optimize=True)
    MM23B += 0.25 * np.einsum("mcek,abeijm->abcijk", H.ab.ovvo, T.aaa, optimize=True)
    MM23B += 0.25 * np.einsum("cmke,abeijm->abcijk", H.bb.voov, T.aab, optimize=True)
    MM23B -= 0.5 * np.einsum("amek,ebcijm->abcijk", H.ab.vovo, T.aab, optimize=True)
    MM23B -= 0.5 * np.einsum("mcie,abemjk->abcijk", H.ab.ovov, T.aab, optimize=True)

    MM23B -= np.transpose(MM23B, (1, 0, 2, 3, 4, 5))
    MM23B -= np.transpose(MM23B, (0, 1, 2, 4, 3, 5))

    return MM23B


def build_L3A_full(L, H, X):

    # < 0 | L1 * H(2) | ijkabc >
    L3A = (9.0 / 36.0) * np.einsum("ai,jkbc->abcijk", L.a, H.aa.oovv, optimize=True)

    # < 0 | L2 * H(2) | ijkabc >
    L3A += (9.0 / 36.0) * np.einsum("bcjk,ia->abcijk", L.aa, H.a.ov, optimize=True)

    L3A += (9.0 / 36.0) * np.einsum("ebij,ekac->abcijk", L.aa, H.aa.vovv, optimize=True)
    L3A -= (9.0 / 36.0) * np.einsum("abmj,ikmc->abcijk", L.aa, H.aa.ooov, optimize=True)

    # < 0 | L3 * H(2) | ijkabc >
    L3A += (3.0 / 36.0) * np.einsum("ea,ebcijk->abcijk", H.a.vv, L.aaa, optimize=True)
    L3A -= (3.0 / 36.0) * np.einsum("im,abcmjk->abcijk", H.a.oo, L.aaa, optimize=True)
    L3A += (9.0 / 36.0) * np.einsum("eima,ebcmjk->abcijk", H.aa.voov, L.aaa, optimize=True)
    L3A += (9.0 / 36.0) * np.einsum("ieam,bcejkm->abcijk", H.ab.ovvo, L.aab, optimize=True)
    L3A += (3.0 / 72.0) * np.einsum("ijmn,abcmnk->abcijk", H.aa.oooo, L.aaa, optimize=True)
    L3A += (3.0 / 72.0) * np.einsum("efab,efcijk->abcijk", H.aa.vvvv, L.aaa, optimize=True)

    L3A += (9.0 / 36.0) * np.einsum("ijeb,ekac->abcijk", H.aa.oovv, X.aa.vovv, optimize=True)
    L3A -= (9.0 / 36.0) * np.einsum("mjab,ikmc->abcijk", H.aa.oovv, X.aa.ooov, optimize=True)

    L3A -= np.transpose(L3A, (0, 1, 2, 3, 5, 4)) # (jk)
    L3A -= np.transpose(L3A, (0, 1, 2, 4, 3, 5)) + np.transpose(L3A, (0, 1, 2, 5, 4, 3)) # (i/jk)
    L3A -= np.transpose(L3A, (0, 2, 1, 3, 4, 5)) # (bc)
    L3A -= np.transpose(L3A, (2, 1, 0, 3, 4, 5)) + np.transpose(L3A, (1, 0, 2, 3, 4, 5)) # (a/bc)

    return L3A


def build_L3B_full(L, H, X):

    # < 0 | L1 * H(2) | ijk~abc~ >
    L3B = np.einsum("ai,jkbc->abcijk", L.a, H.ab.oovv, optimize=True)
    L3B += 0.25 * np.einsum("ck,ijab->abcijk", L.b, H.aa.oovv, optimize=True)

    # < 0 | L2 * H(2) | ijk~abc~ >
    L3B += np.einsum("bcjk,ia->abcijk", L.ab, H.a.ov, optimize=True)
    L3B += 0.25 * np.einsum("abij,kc->abcijk", L.aa, H.b.ov, optimize=True)

    L3B += 0.5 * np.einsum("ekbc,aeij->abcijk", H.ab.vovv, L.aa, optimize=True)
    L3B -= 0.5 * np.einsum("jkmc,abim->abcijk", H.ab.ooov, L.aa, optimize=True)
    L3B += np.einsum("ieac,bejk->abcijk", H.ab.ovvv, L.ab, optimize=True)
    L3B -= np.einsum("ikam,bcjm->abcijk", H.ab.oovo, L.ab, optimize=True)
    L3B += 0.5 * np.einsum("eiba,ecjk->abcijk", H.aa.vovv, L.ab, optimize=True)
    L3B -= 0.5 * np.einsum("jima,bcmk->abcijk", H.aa.ooov, L.ab, optimize=True)

    L3B += 0.5 * np.einsum("ekbc,ijae->abcijk", X.ab.vovv, H.aa.oovv, optimize=True)
    L3B -= 0.5 * np.einsum("jkmc,imab->abcijk", X.ab.ooov, H.aa.oovv, optimize=True)
    L3B += np.einsum("ieac,jkbe->abcijk", X.ab.ovvv, H.ab.oovv, optimize=True)
    L3B -= np.einsum("ikam,jmbc->abcijk", X.ab.oovo, H.ab.oovv, optimize=True)
    L3B += 0.5 * np.einsum("eiba,jkec->abcijk", X.aa.vovv, H.ab.oovv, optimize=True)
    L3B -= 0.5 * np.einsum("jima,mkbc->abcijk", X.aa.ooov, H.ab.oovv, optimize=True)

    # < 0 | L3 * H(2) | ijk~abc~ >
    L3B -= 0.5 * np.einsum("im,abcmjk->abcijk", H.a.oo, L.aab, optimize=True)
    L3B -= 0.25 * np.einsum("km,abcijm->abcijk", H.b.oo, L.aab, optimize=True)
    L3B += 0.5 * np.einsum("ea,ebcijk->abcijk", H.a.vv, L.aab, optimize=True)
    L3B += 0.25 * np.einsum("ec,abeijk->abcijk", H.b.vv, L.aab, optimize=True)
    L3B += 0.125 * np.einsum("ijmn,abcmnk->abcijk", H.aa.oooo, L.aab, optimize=True)
    L3B += 0.5 * np.einsum("jkmn,abcimn->abcijk", H.ab.oooo, L.aab, optimize=True)
    L3B += 0.125 * np.einsum("efab,efcijk->abcijk", H.aa.vvvv, L.aab, optimize=True)
    L3B += 0.5 * np.einsum("efbc,aefijk->abcijk", H.ab.vvvv, L.aab, optimize=True)
    L3B += np.einsum("eima,ebcmjk->abcijk", H.aa.voov, L.aab, optimize=True)
    L3B += np.einsum("ieam,becjmk->abcijk", H.ab.ovvo, L.abb, optimize=True)
    L3B += 0.25 * np.einsum("ekmc,abeijm->abcijk", H.ab.voov, L.aaa, optimize=True)
    L3B += 0.25 * np.einsum("ekmc,abeijm->abcijk", H.bb.voov, L.aab, optimize=True)
    L3B -= 0.5 * np.einsum("ekam,ebcijm->abcijk", H.ab.vovo, L.aab, optimize=True)
    L3B -= 0.5 * np.einsum("iemc,abemjk->abcijk", H.ab.ovov, L.aab, optimize=True)

    L3B -= np.transpose(L3B, (1, 0, 2, 3, 4, 5))
    L3B -= np.transpose(L3B, (0, 1, 2, 4, 3, 5))

    return L3B
