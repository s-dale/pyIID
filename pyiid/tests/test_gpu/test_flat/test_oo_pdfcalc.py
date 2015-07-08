__author__ = 'christopher'
import numpy as np
from ase.atoms import Atoms
from numpy.testing import assert_allclose

from pyiid.wrappers.elasticscatter import ElasticScatter, wrap_atoms
from pyiid.tests import generate_experiment, setup_atoms
from pyiid.testing.decorators import known_fail_if
from pyiid.calc.pdfcalc import PDFCalc

n = 2000


def test_rw():
    atoms1, atoms2 = setup_atoms(n), setup_atoms(n)
    scat = ElasticScatter()
    scat.set_processor('Multi-GPU', 'test_flat')
    gobs = scat.get_pdf(atoms1)
    calc = PDFCalc(obs_data=gobs, scatter=scat, potential='rw')
    atoms2.set_calculator(calc)
    rw = atoms2.get_potential_energy()
    # print rw
    assert rw != 0.0


def test_chi_sq():
    atoms1, atoms2 = setup_atoms(n), setup_atoms(n)
    scat = ElasticScatter()
    scat.set_processor('Multi-GPU', 'test_flat')
    gobs = scat.get_pdf(atoms1)
    calc = PDFCalc(obs_data=gobs, scatter=scat, potential='chi_sq')
    atoms2.set_calculator(calc)
    chi_sq = atoms2.get_potential_energy()
    # print chi_sq
    assert chi_sq != 0.0
    # assert False


def test_grad_rw():
    atoms1, atoms2 = setup_atoms(n), setup_atoms(n)
    scat = ElasticScatter()
    scat.set_processor('Multi-GPU', 'test_flat')
    gobs = scat.get_pdf(atoms1)
    calc = PDFCalc(obs_data=gobs, scatter=scat, potential='rw')
    atoms2.set_calculator(calc)
    forces = atoms2.get_forces()
    com = atoms2.get_center_of_mass()
    for i in range(len(atoms2)):
        dist = atoms2[i].position - com
        np.alltrue(np.cross(dist, forces[i]) != np.zeros(3))


def test_grad_chi_sq():
    atoms1, atoms2 = setup_atoms(n), setup_atoms(n)
    scat = ElasticScatter()
    scat.set_processor('Multi-GPU', 'test_flat')
    gobs = scat.get_pdf(atoms1)
    calc = PDFCalc(obs_data=gobs, scatter=scat, potential='chi_sq')
    atoms2.set_calculator(calc)
    forces = atoms2.get_forces()
    com = atoms2.get_center_of_mass()
    for i in range(len(atoms2)):
        dist = atoms2[i].position - com
        # print dist, forces[i], np.cross(dist, forces[i])
        np.alltrue(np.cross(dist, forces[i]) != np.zeros(3))


if __name__ == '__main__':
    import nose

    nose.runmodule(argv=['-s', '--with-doctest'], exit=False)