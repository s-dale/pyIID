import numpy as np
from ase.atoms import Atoms
from pyiid.experiments.elasticscatter import wrap_atoms
from numpy.testing import assert_allclose
from itertools import *
import os
from copy import deepcopy as dc
import random
from pyiid.testing.decorators import *

from pyiid.calc.spring_calc import Spring

srfit = False
try:
    from diffpy.Structure.structure import Structure
    from diffpy.Structure.atom import Atom as dAtom
    from diffpy.srreal.pdfcalculator import DebyePDFCalculator

    srfit = True
except:
    pass
__author__ = 'christopher'

if srfit:
    def convert_atoms_to_stru(atoms):
        """
        Convert between ASE and Diffpy structural objects

        Parameters:
        -----------
        atoms: ase.Atoms object

        Return:
        diffpy.Structure object:
        """
        diffpy_atoms = []
        symbols = atoms.get_chemical_symbols()
        q = atoms.get_positions()
        tags = atoms.get_tags()
        for symbol, xyz, tag, in zip(symbols, q, tags):
            d_atom = dAtom(symbol, xyz=xyz,
                           label=tag, occupancy=1)
            diffpy_atoms.append(d_atom)
        stru = Structure(diffpy_atoms)
        return stru


    def update_stru(new_atoms, stru):
        aatomq = new_atoms.get_positions()
        datomq = np.reshape([datom.xyz for datom in stru], (len(new_atoms), 3))
        # aatome = new_atoms.get_chemical_symbols()
        # datome = np.array([datom.element for datom in stru])
        changedq = np.in1d(aatomq, datomq).reshape((len(new_atoms), 3))

        changed_array = np.sum(changedq, 1) != 3
        stru[changed_array].xyz = new_atoms[changed_array].get_positions()
        # for i in len(changed_array):
        #     if changed_array[i] == True:
        #         stru[i]._set_xyz_cartn(new_atoms[i].position)
        # changed_list = []
        # for i in len(new_atoms):
        #     if np.sum(changedq[i, :]) != 3:
        #         changed_list.append(i)
        # for j in changed_list:
        #     stru[j]._set_xyz_cartn(new_atoms[j].position)
        return stru


def setup_atoms(n):
    """
    Generate a configuration of n gold atoms with random positions
    """
    q = np.random.random((n, 3)) * 10
    atoms = Atoms('Au' + str(int(n)), q)
    atoms.center()
    return atoms


def setup_double_atoms(n):
    """
    Generate two configuration of n gold atoms with random positions
    """
    q = np.random.random((n, 3)) * 10
    atoms = Atoms('Au' + str(int(n)), q)

    q2 = np.random.random((n, 3)) * 10
    atoms2 = Atoms('Au' + str(int(n)), q2)
    atoms.center()
    atoms2.center()
    return atoms, atoms2


def generate_experiment():
    """
    Generate elastic scattering experiments which are reasonable but random
    """
    exp_dict = {}
    exp_keys = ['qmin', 'qmax', 'qbin', 'rmin', 'rmax', 'rstep']
    exp_ranges = [(0, 1.5), (19., 25.), (.8, .12), (0., 2.5), (30., 50.),
                  (.005, .015)]
    for n, k in enumerate(exp_keys):
        exp_dict[k] = np.random.uniform(exp_ranges[n][0], exp_ranges[n][1])
    exp_dict['sampling'] = random.choice(['full', 'ns'])
    return exp_dict


def setup_atomic_square():
    """
    Setup squares of 4 gold atoms with known positions
    :return:
    """
    atoms1 = Atoms('Au4', [[0, 0, 0], [3, 0, 0], [0, 3, 0], [3, 3, 0]])
    atoms2 = atoms1.copy()
    scale = .75
    atoms2.positions *= scale
    atoms1.center()
    atoms2.center()
    return atoms1, atoms2


def stats_check(ans1, ans2, rtol=1e-7, atol=0):
    print 'bulk statistics:'
    print 'max', np.max(np.abs(ans2 - ans1)),
    print 'min', np.min(np.abs(ans2 - ans1)),
    print 'men', np.mean(np.abs(ans2 - ans1)),
    print 'med', np.median(np.abs(ans2 - ans1)),
    print 'std', np.std(np.abs(ans2 - ans1))

    if isinstance(ans1, type(np.asarray([1]))):
        print 'normalized max', np.max(np.abs(ans2 - ans1)) / ans2[
            np.unravel_index(np.argmax(np.abs(ans2 - ans1)), ans2.shape)]
        fails = np.where(np.abs(ans1 - ans2) >= atol + rtol * np.abs(ans2))
        print '\n allclose failures'
        print zip(ans1[fails].tolist(), ans2[fails].tolist())
        print '\n allclose internals'
        print zip(np.abs(ans1[fails] - ans2[fails]).tolist(),
                  (atol + rtol * np.abs(ans2[fails])).tolist())
        print '\n', 'without atol rtol = ', '\n'
        print np.abs(ans1[fails] - ans2[fails]) / np.abs(ans2[fails])
        print 'without rtol atol = ', '\n'
        print np.abs(ans1[fails] - ans2[fails])
    else:
        print np.abs(ans1 - ans2)
        print atol + rtol * np.abs(ans2)
        print 'without atol'
        print rtol * np.abs(ans2)
        print 'without atol rtol =', np.abs(ans1 - ans2) / np.abs(ans2)


# Setup lists of test variables
test_exp = [None]
test_atom_squares = [setup_atomic_square()]
test_potentials = [
    ('rw', .9),
    ('chi_sq', 1)
]
test_qbin = [.1]
test_spring_kwargs = [{'k': 100, 'rt': 5., 'sp_type': 'rep'},
                      {'k': 100, 'rt': 1., 'sp_type': 'com'},
                      {'k': 100, 'rt': 1., 'sp_type': 'att'}]

test_calcs = [
    Spring(**t_kwargs) for t_kwargs in test_spring_kwargs
    ]
test_calcs.extend(['FQ', 'PDF'])

# Travis CI has certain restrictions on memory and GPU availability so we
# change the size of the tests to run
travis = False
if os.getenv('TRAVIS') or True:
    travis = True
    # use a smaller test size otherwise travis stalls
    ns = [10, 100]
    test_exp.extend([generate_experiment() for i in range(3)])
    test_atoms = [setup_atoms(int(n)) for n in ns]
    test_double_atoms = [setup_double_atoms(int(n)) for n in ns]

    # Travis doesn't have GPUs so only CPU testing
    proc_alg_pairs = list(product(['CPU'], ['nxn', 'flat']))
    comparison_pro_alg_pairs = list(combinations(proc_alg_pairs, 2))

else:
    ns = np.logspace(1, 3, 3)
    test_exp.extend([generate_experiment() for i in range(3)])
    test_atoms = [setup_atoms(int(n)) for n in ns]
    test_double_atoms = [setup_double_atoms(int(n)) for n in ns]
    proc_alg_pairs = [('CPU', 'flat'), ('Multi-GPU', 'flat'),
                      # ('CPU', 'nxn'),
                      ]

    # Note there is only one CPU nxn comparison test, the CPU nxn code is
    # rather slow, thus we test it against the flattened Multi core CPU code,
    # which is much faster.  Then we run all tests agains the CPU flat kernels.
    # Thus it is imperative that the flat CPU runs with no errors.

    comparison_pro_alg_pairs = [(('CPU', 'flat'), ('Multi-GPU', 'flat'))
                                # (('CPU', 'nxn'), ('CPU', 'flat')),
                                ]
