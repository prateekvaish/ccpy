"""In this script, we test out the idea of using the 'amplitude-driven' approach
to constructing the sparse triples projection < ijkabc | (H(2) * T3)_C | 0 >, where
T3 is sparse and defined over a given list of triples."""
import numpy as np
import time

from ccpy.interfaces.pyscf_tools import load_pyscf_integrals
from ccpy.drivers.driver import cc_driver
from ccpy.models.calculation import Calculation
from ccpy.hbar.hbar_ccsd import get_ccsd_intermediates
from ccpy.utilities.updates import ccp_quadratic_loops_direct

def get_T3_list(T):

    nua, noa = T.a.shape
    nub, nob = T.b.shape

    T3_excitations = {"aaa" : [], "aab" : [], "abb" : [], "bbb" : []}
    T3_amplitudes = {"aaa" : [], "aab" : [], "abb" : [], "bbb" : []}

    for a in range(nua):
        for b in range(a + 1, nua):
            for c in range(b + 1, nua):
                for i in range(noa):
                    for j in range(i + 1, noa):
                        for k in range(j + 1, noa):
                            T3_excitations["aaa"].append([a+1, b+1, c+1, i+1, j+1, k+1])
                            T3_amplitudes["aaa"].append(T.aaa[a, b, c, i, j, k])
    for a in range(nua):
        for b in range(a + 1, nua):
            for c in range(nub):
                for i in range(noa):
                    for j in range(i + 1, noa):
                        for k in range(nob):
                            T3_excitations["aab"].append([a+1, b+1, c+1, i+1, j+1, k+1])
                            T3_amplitudes["aab"].append(T.aab[a, b, c, i, j, k])
    for a in range(nua):
        for b in range(nub):
            for c in range(b + 1, nub):
                for i in range(noa):
                    for j in range(nob):
                        for k in range(j + 1, nob):
                            T3_excitations["abb"].append([a+1, b+1, c+1, i+1, j+1, k+1])
                            T3_amplitudes["abb"].append(T.abb[a, b, c, i, j, k])
    for a in range(nub):
        for b in range(a + 1, nub):
            for c in range(b + 1, nub):
                for i in range(nob):
                    for j in range(i + 1, nob):
                        for k in range(j + 1, nob):
                            T3_excitations["bbb"].append([a+1, b+1, c+1, i+1, j+1, k+1])
                            T3_amplitudes["bbb"].append(T.bbb[a, b, c, i, j, k])

    for key in T3_excitations.keys():
        T3_excitations[key] = np.asarray(T3_excitations[key])
        T3_amplitudes[key] = np.asarray(T3_amplitudes[key])

    return T3_excitations, T3_amplitudes

def contract_vt3_exact(H0, H, T):

    nua, noa = T.a.shape
    nub, nob = T.b.shape

    I2A_vvov = (
        H.aa.vvov - 0.5 * np.einsum("mnef,abfimn->abie", H.aa.oovv, T.aaa, optimize=True)
                  - np.einsum("mnef,abfimn->abie", H.ab.oovv, T.aab, optimize=True)
    )
    I2A_vooo = (
        H.aa.vooo + 0.5 * np.einsum("mnef,aefijn->amij", H.aa.oovv, T.aaa, optimize=True)
                  + np.einsum("mnef,aefijn->amij", H.ab.oovv, T.aab, optimize=True)
                  - np.einsum("me,aeij->amij", H.a.ov, T.aa, optimize=True)
    )
    I2B_vvvo =(
        H.ab.vvvo - 0.5 * np.einsum("mnef,afbmnj->abej", H.aa.oovv, T.aab, optimize=True)
                  - np.einsum("mnef,afbmnj->abej", H.ab.oovv, T.abb, optimize=True)
    )
    I2B_ovoo = (
        H.ab.ovoo + 0.5 * np.einsum("mnef,efbinj->mbij", H.aa.oovv, T.aab, optimize=True)
                  + np.einsum("mnef,efbinj->mbij", H.ab.oovv, T.abb, optimize=True)
                  - np.einsum("me,ecjk->mcjk", H.a.ov, T.ab, optimize=True)
    )
    I2B_vvov = (
        H.ab.vvov - np.einsum("nmfe,afbinm->abie", H.ab.oovv, T.aab, optimize=True)
                  - 0.5 * np.einsum("nmfe,afbinm->abie", H.bb.oovv, T.abb, optimize=True)
    )
    I2B_vooo = (
        H.ab.vooo + np.einsum("nmfe,afeinj->amij", H.ab.oovv, T.aab, optimize=True)
                  + 0.5 * np.einsum("nmfe,afeinj->amij", H.bb.oovv, T.abb, optimize=True)
                  - np.einsum("me,aeik->amik", H.b.ov, T.ab, optimize=True)
    )
    I2C_vvov = (
        H.bb.vvov - 0.5 * np.einsum("mnef,abfimn->abie", H.bb.oovv, T.bbb, optimize=True)
                  - np.einsum("nmfe,fbanmi->abie", H.ab.oovv, T.abb, optimize=True)
    )
    I2C_vooo = (
        H.bb.vooo + 0.5 * np.einsum("mnef,aefijn->amij", H.bb.oovv, T.bbb, optimize=True)
                  + np.einsum("nmfe,feanji->amij", H.ab.oovv, T.abb, optimize=True)
                  - np.einsum("me,aeij->amij", H.b.ov, T.bb, optimize=True)
    )

    # MM(2,3)
    x3a = -0.25 * np.einsum("amij,bcmk->abcijk", I2A_vooo, T.aa, optimize=True)
    x3a += 0.25 * np.einsum("abie,ecjk->abcijk", I2A_vvov, T.aa, optimize=True)
    # (Hbar*T3)
    x3a -= (3.0 / 36.0) * np.einsum("mi,abcmjk->abcijk", H.a.oo, T.aaa, optimize=True)
    x3a += (3.0 / 36.0) * np.einsum("ae,ebcijk->abcijk", H.a.vv, T.aaa, optimize=True)
    x3a += (1.0 / 24.0) * np.einsum("mnij,abcmnk->abcijk", H.aa.oooo, T.aaa, optimize=True) # (k/ij) = 3
    x3a += (1.0 / 24.0) * np.einsum("abef,efcijk->abcijk", H.aa.vvvv, T.aaa, optimize=True) # (c/ab) = 3
    x3a += 0.25 * np.einsum("cmke,abeijm->abcijk", H.aa.voov, T.aaa, optimize=True) # (c/ij)(k/ij) = 9
    x3a += 0.25 * np.einsum("cmke,abeijm->abcijk", H.ab.voov, T.aab, optimize=True) # (c/ij)(k/ij) = 9

    x3a -= np.transpose(x3a, (0, 1, 2, 3, 5, 4)) # (jk)
    x3a -= np.transpose(x3a, (0, 1, 2, 4, 3, 5)) + np.transpose(x3a, (0, 1, 2, 5, 4, 3)) # (i/jk)
    x3a -= np.transpose(x3a, (0, 2, 1, 3, 4, 5)) # (bc)
    x3a -= np.transpose(x3a, (2, 1, 0, 3, 4, 5)) + np.transpose(x3a, (1, 0, 2, 3, 4, 5)) # (a/bc)

    # MM(2,3)
    x3b = 0.5 * np.einsum("bcek,aeij->abcijk", I2B_vvvo, T.aa, optimize=True)
    x3b -= 0.5 * np.einsum("mcjk,abim->abcijk", I2B_ovoo, T.aa, optimize=True)
    x3b += np.einsum("acie,bejk->abcijk", I2B_vvov, T.ab, optimize=True)
    x3b -= np.einsum("amik,bcjm->abcijk", I2B_vooo, T.ab, optimize=True)
    x3b += 0.5 * np.einsum("abie,ecjk->abcijk", I2A_vvov, T.ab, optimize=True)
    x3b -= 0.5 * np.einsum("amij,bcmk->abcijk", I2A_vooo, T.ab, optimize=True)
    # (Hbar*T3)
    x3b -= 0.5 * np.einsum("mi,abcmjk->abcijk", H.a.oo, T.aab, optimize=True)
    x3b -= 0.25 * np.einsum("mk,abcijm->abcijk", H.b.oo, T.aab, optimize=True)
    #x3b += 0.5 * np.einsum("ae,ebcijk->abcijk", H.a.vv, T.aab, optimize=True)
    #x3b += 0.25 * np.einsum("ce,abeijk->abcijk", H.b.vv, T.aab, optimize=True)
    #x3b += 0.125 * np.einsum("mnij,abcmnk->abcijk", H.aa.oooo, T.aab, optimize=True)
    #x3b += 0.5 * np.einsum("mnjk,abcimn->abcijk", H.ab.oooo, T.aab, optimize=True)
    #x3b += 0.125 * np.einsum("abef,efcijk->abcijk", H.aa.vvvv, T.aab, optimize=True)
    #x3b += 0.5 * np.einsum("bcef,aefijk->abcijk", H.ab.vvvv, T.aab, optimize=True)
    #x3b += np.einsum("amie,ebcmjk->abcijk", H.aa.voov, T.aab, optimize=True)
    #x3b += np.einsum("amie,becjmk->abcijk", H.ab.voov, T.abb, optimize=True)
    #x3b += 0.25 * np.einsum("mcek,abeijm->abcijk", H.ab.ovvo, T.aaa, optimize=True)
    #x3b += 0.25 * np.einsum("cmke,abeijm->abcijk", H.bb.voov, T.aab, optimize=True)
    #x3b -= 0.5 * np.einsum("amek,ebcijm->abcijk", H.ab.vovo, T.aab, optimize=True)
    #x3b -= 0.5 * np.einsum("mcie,abemjk->abcijk", H.ab.ovov, T.aab, optimize=True)

    x3b -= np.transpose(x3b, (1, 0, 2, 3, 4, 5)) # (ab)
    x3b -= np.transpose(x3b, (0, 1, 2, 4, 3, 5)) # (ij)

    return x3a, x3b

def contract_vt3_fly(H, H0, T, T3_excitations, T3_amplitudes):

    nua, noa = T.a.shape
    nub, nob = T.b.shape

    # build adjusted intermediates
    I2A_vooo = H.aa.vooo - np.einsum("me,aeij->amij", H.a.ov, T.aa, optimize=True)
    I2B_vooo = H.ab.vooo - np.einsum("me,aeik->amik", H.b.ov, T.ab, optimize=True)
    I2B_ovoo = H.ab.ovoo - np.einsum("me,ecjk->mcjk", H.a.ov, T.ab, optimize=True)
    I2C_vooo = H.bb.vooo - np.einsum("me,aeij->amij", H.b.ov, T.bb, optimize=True)

    # save the input T vectors; these get modififed by Fortran calls even if output is not set
    t1a_amps = T.a.copy()
    t1b_amps = T.b.copy()
    t2a_amps = T.aa.copy()
    t2b_amps = T.ab.copy()
    t2c_amps = T.bb.copy()
    t3a_amps = T3_amplitudes["aaa"].copy()
    t3b_amps = T3_amplitudes["aab"].copy()
    t3c_amps = T3_amplitudes["abb"].copy()
    t3d_amps = T3_amplitudes["bbb"].copy()

    t3_aaa, resid_aaa = ccp_quadratic_loops_direct.ccp_quadratic_loops_direct.update_t3a_p(
        T3_amplitudes["aaa"],
        T3_excitations["aaa"].T, T3_excitations["aab"].T,
        T.aa,
        T3_amplitudes["aab"],
        H.a.oo, H.a.vv,
        H0.aa.oovv, H.aa.vvov, I2A_vooo,
        H.aa.oooo, H.aa.voov, H.aa.vvvv,
        H0.ab.oovv, H.ab.voov,
        H0.a.oo, H0.a.vv,
        0.0
    )
    T3_amplitudes["aaa"] = t3a_amps.copy()

    t3_aab, resid_aab = ccp_quadratic_loops_direct.ccp_quadratic_loops_direct.update_t3b_p(
        T3_amplitudes["aab"],
        T3_excitations["aaa"].T, T3_excitations["aab"].T, T3_excitations["abb"].T,
        T.aa, T.ab,
        T3_amplitudes["aaa"], T3_amplitudes["abb"],
        H.a.oo, H.a.vv, H.b.oo, H.b.vv,
        H0.aa.oovv, H.aa.vvov, I2A_vooo, H.aa.oooo, H.aa.voov, H.aa.vvvv,
        H0.ab.oovv, H.ab.vvov, H.ab.vvvo, I2B_vooo, I2B_ovoo, 
        H.ab.oooo, H.ab.voov,H.ab.vovo, H.ab.ovov, H.ab.ovvo, H.ab.vvvv,
        H0.bb.oovv, H.bb.voov,
        H0.a.oo, H0.a.vv, H0.b.oo, H0.b.vv,
        0.0
    )
    T3_amplitudes["aab"] = t3b_amps.copy()

    return t3_aaa, resid_aaa, t3_aab, resid_aab

# def contract_vt3_fly(H, H0, T, T3_excitations, T3_amplitudes):
#
#     nua, noa = T.a.shape
#     nub, nob = T.b.shape
#
#     # Residual containers
#     resid_aaa = np.zeros(len(T3_amplitudes["aaa"]))
#     resid_aab = np.zeros(len(T3_amplitudes["aab"]))
#     resid_abb = np.zeros(len(T3_amplitudes["abb"]))
#     resid_bbb = np.zeros(len(T3_amplitudes["bbb"]))
#
#     # Loop over aaa determinants
#     for idet in range(len(T3_amplitudes["aaa"])):
#
#         a, b, c, i, j, k = [x for x in T3_excitations["aaa"][idet]]
#
#         for jdet in range(len(T3_amplitudes["aaa"])):
#
#             d, e, f, l, m, n = [x for x in T3_excitations["aaa"][jdet]]
#
#             # Get the particular aaa T3 amplitude
#             t_amp = T3_amplitudes["aaa"][jdet]
#
#             hmatel = 0.0
#             hmatel += hbar_matrix_elements.hbar_matrix_elements.aaa_oo_aaa(i, j, k, a, b, c, l, m, n, d, e, f, H.a.oo)
#             if hmatel != 0.0:
#                 print(a,b,c,i,j,k,d,e,f,l,m,n,hmatel)
#             #hmatel += hbar_matrix_elements.hbar_matrix_elements.aaa_vv_aaa(i, j, k, a, b, c, l, m, n, d, e, f, H.a.vv)
#             #hmatel += hbar_matrix_elements.hbar_matrix_elements.aaa_oooo_aaa(i, j, k, a, b, c, l, m, n, d, e, f, H.aa.oooo)
#             #hmatel += hbar_matrix_elements.hbar_matrix_elements.aaa_vvvv_aaa(i, j, k, a, b, c, l, m, n, d, e, f, H.aa.vvvv)
#
#             resid_aaa[idet] += hmatel * t_amp
#
#     return resid_aaa

if __name__ == "__main__":

    from pyscf import gto, scf
    mol = gto.Mole()

    methylene = """
                    C 0.0000000000 0.0000000000 -0.1160863568
                    H -1.8693479331 0.0000000000 0.6911102033
                    H 1.8693479331 0.0000000000  0.6911102033
     """

    fluorine = """
                    F 0.0000000000 0.0000000000 -2.66816
                    F 0.0000000000 0.0000000000  2.66816
    """

    mol.build(
        atom=methylene,
        basis="ccpvdz",
        symmetry="C2V",
        spin=0, 
        charge=0,
        unit="Bohr",
        cart=True,
    )
    mf = scf.ROHF(mol).run()

    system, H = load_pyscf_integrals(mf, nfrozen=1)
    system.print_info()

    calculation = Calculation(calculation_type="ccsdt")
    T, cc_energy, converged = cc_driver(calculation, system, H)
    hbar = get_ccsd_intermediates(T, H)

    T3_excitations, T3_amplitudes = get_T3_list(T)

    # Get the expected result for the contraction, computed using full T_ext
    print("   Exact H*T3 contraction", end="")
    t1 = time.time()
    x3_aaa_exact, x3_aab_exact = contract_vt3_exact(H, hbar, T)
    print(" (Completed in ", time.time() - t1, "seconds)")

    # Get the on-the-fly contraction result
    print("   On-the-fly H*T3 contraction", end="")
    t1 = time.time()
    t3_aaa, x3_aaa, t3_aab, x3_aab = contract_vt3_fly(hbar, H, T, T3_excitations, T3_amplitudes)
    print(" (Completed in ", time.time() - t1, "seconds)")

    print("")
    nua, noa = T.a.shape
    nub, nob = T.b.shape

    flag = True
    err_cum = 0.0
    for idet in range(len(T3_amplitudes["aaa"])):
        a, b, c, i, j, k = [x - 1 for x in T3_excitations["aaa"][idet]]
        denom = (
                    H.a.oo[i, i] + H.a.oo[j, j] + H.a.oo[k, k]
                   -H.a.vv[a, a] - H.a.vv[b, b] - H.a.vv[c, c]
        )
        error = (x3_aaa[idet] - x3_aaa_exact[a, b, c, i, j, k])/denom
        err_cum += abs(error)
        if abs(error) > 1.0e-012:
            #print(a, b, c, i, j, k, "Expected = ", x3_aaa_exact[a, b, c, i, j, k], "Got = ", x3_aaa[idet])
            flag = False
    if flag:
        print("T3A update passed!", "Cumulative Error = ", err_cum)
    else:
        print("T3A update FAILED!", "Cumulative Error = ", err_cum)
    
    flag = True
    err_cum = 0.0
    for idet in range(len(T3_amplitudes["aab"])):
        a, b, c, i, j, k = [x - 1 for x in T3_excitations["aab"][idet]]
        denom = (
                    H.a.oo[i, i] + H.a.oo[j, j] + H.b.oo[k, k]
                   -H.a.vv[a, a] - H.a.vv[b, b] - H.b.vv[c, c]
        )
        error = (x3_aab[idet] - x3_aab_exact[a, b, c, i, j, k])/denom
        err_cum += abs(error)
        if abs(error) > 1.0e-010:
            flag = False
    if flag:
        print("T3B update passed!", "Cumulative Error = ", err_cum)
    else:
        print("T3B update FAILED!", "Cumulative Error = ", err_cum)
    
    # flag = True
    # err_cum = 0.0
    # for idet in range(len(T3_amplitudes["abb"])):
    #     a, b, c, i, j, k = [x - 1 for x in T3_excitations["abb"][idet]]
    #     denom = (
    #                 H.a.oo[i, i] + H.b.oo[j, j] + H.b.oo[k, k]
    #                -H.a.vv[a, a] - H.b.vv[b, b] - H.b.vv[c, c]
    #     )
    #     error = (x3_abb[idet] - x3_abb_exact[a, b, c, i, j, k])/denom
    #     err_cum += abs(error)
    #     if abs(error) > 1.0e-010:
    #         flag = False
    # if flag:
    #     print("T3C update passed!", "Cumulative Error = ", err_cum)
    # else:
    #     print("T3C update FAILED!", "Cumulative Error = ", err_cum)
    #
    # flag = True
    # err_cum = 0.0
    # for idet in range(len(T3_amplitudes["bbb"])):
    #     a, b, c, i, j, k = [x - 1 for x in T3_excitations["bbb"][idet]]
    #     denom = (
    #                 H.b.oo[i, i] + H.b.oo[j, j] + H.b.oo[k, k]
    #                -H.b.vv[a, a] - H.b.vv[b, b] - H.b.vv[c, c]
    #     )
    #     error = (x3_bbb[idet] - x3_bbb_exact[a, b, c, i, j, k])/denom
    #     err_cum += abs(error)
    #     if abs(error) > 1.0e-010:
    #         flag = False
    # if flag:
    #     print("T3D update passed!", "Cumulative Error = ", err_cum)
    # else:
    #     print("T3D update FAILED!", "Cumulative Error = ", err_cum)

