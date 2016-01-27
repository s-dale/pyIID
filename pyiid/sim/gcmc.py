from copy import deepcopy as dc
from time import time
import numpy as np
from ase.atom import Atom
from ase.units import *
from pyiid.sim import Ensemble
from ase.calculators.calculator import Calculator
from ase.constraints import FixAtoms
from ase.optimize import BFGS, FIRE

__author__ = 'christopher'


def add_atom(atoms, chem_potentials, beta, random_state, resolution=None,
             voxel_weighting=False):
    """
    Perform a GCMC atomic addition

    Parameters
    ----------
    atoms: ase.Atoms object
        The atomic configuration
    chem_potentials: dict
        A dictionary of {"Chemical Symbol": mu} where mu is a float denoting
        the chemical potential
    beta: float
        The thermodynamic beta
    random_state: np.random.RandomState object
        The random state to be used
    resolution: float or ndarray, optional
        If used denote the resolution for the voxels
    voxel_weighting: True or function, optional
        If True use the atoms' calculator's calculate_voxel_energy
        If a function perform a call on that function, function(atoms)
        Note that this must be paired with a resolution

    Returns
    -------
    atoms or None:
        If the new configuration is accepted then the new atomic configuration
        is returned, else None

    """
    # make the proposed system
    atoms_prime = dc(atoms)

    # make new atom
    new_symbol = np.random.choice(chem_potentials.keys())
    prop_atom = Atom(new_symbol, [0, 0, 0])
    e0 = atoms.get_potential_energy()
    vi = None
    prob_i = None
    if resolution is None:
        new_position = np.random.uniform(0, np.max(atoms.get_cell(), 0))
    else:
        c = np.int32(np.ceil(np.diagonal(atoms.get_cell()) / resolution))
        if voxel_weighting is True:
            # Get the voxel energy using exponential weighting
            voxel_nrg = atoms.calc.calculate_voxel_energy(atoms, prop_atom,
                                                          resolution)
            prob = np.exp(np.float64(-beta * (voxel_nrg - e0)))
            prob -= np.min(prob)
            prob /= np.sum(prob)
            qvr = np.random.choice(prob.size, p=prob.ravel())
            prob_i = prob.ravel()[qvr]
            vi = np.product(resolution)
        elif isinstance(voxel_weighting, Calculator):
            vw_e0 = voxel_weighting.calculate_energy(atoms)
            voxel_nrg = voxel_weighting.calculate_voxel_energy(atoms,
                                                               prop_atom,
                                                               resolution)
            prob = np.exp(np.float64(-beta * (voxel_nrg - vw_e0)))
            if np.sum(prob) == np.zeros(1):
                print 'Error in voxel weighting falling back on unweighted ' \
                      'voxels'
                qvr = np.random.choice(np.product(c))
                prob_i = 1. / np.product(c)
                vi = np.product(resolution)
            else:
                prob -= np.min(prob)
                prob /= np.sum(prob)
                qvr = np.random.choice(prob.size, p=prob.ravel())
                prob_i = prob.ravel()[qvr]
                vi = np.product(resolution)
        else:
            # Use voxels for resolution
            qvr = np.random.choice(np.product(c))
            prob_i = 1. / np.product(c)
            vi = np.product(resolution)
        qv = np.asarray(np.unravel_index(qvr, c))
        new_position = (qv + random_state.uniform(0, 1, 3)) * resolution
    new_atom = Atom(new_symbol, np.asarray(new_position))

    # append new atom to system
    atoms_prime.append(new_atom)

    # optimize new atom position
    '''
    print 'pre minimization position', new_position
    print 'Pre minimization energy', atoms_prime.get_potential_energy()
    fixed = FixAtoms(range(0, len(atoms_prime) - 1))
    atoms_prime.set_constraint(fixed)
    dyn = BFGS(atoms_prime)
    # dyn = FIRE(atoms_prime)
    dyn.run(steps=30, fmax=1e-2)
    atoms_prime.set_constraint()
    print 'post minimization position', atoms_prime[-1].position
    print 'Post minimization energy', atoms_prime.get_potential_energy()
    print 'Existing energy', e0
    # '''

    # get new energy
    delta_energy = atoms_prime.get_potential_energy() - e0
    # get chemical potential
    mu = chem_potentials[new_symbol]
    # calculate acceptance
    # TODO: need to write the proper correction to the MH criteria
    print '\t\taddition delta energy', delta_energy
    # print '\t\taddition exp', np.exp(-1. * beta * delta_energy + beta * mu)
    if vi is None or True:
        if np.random.random() < np.exp(
                min([0, -1. * beta * delta_energy + beta * mu])):
            return atoms_prime
        else:
            return None
    else:
        if np.random.random() < np.exp(
                min([0, np.log(
                            vi / prob_i) - 1. * beta * delta_energy + beta * mu])):
            return atoms_prime
        else:
            return None


def del_atom(atoms, chem_potentials, beta, random_state):
    """

    Parameters
    ----------
    atoms: ase.Atoms object
        The atomic configuration
    chem_potentials: dict
        A dictionary of {"Chemical Symbol": mu} where mu is a float denoting
        the chemical potential
    beta: float
        The thermodynamic beta
    random_state: np.random.RandomState object
        The random state to be used

    Returns
    -------
    atoms or None:
        If the new configuration is accepted then the new atomic configuration
        is returned, else None


    """
    if len(atoms) <= 1:
        return None
    # make the proposed system
    atoms_prime = dc(atoms)
    e0 = atoms.get_potential_energy()
    del_atom_index = random_state.choice(range(len(atoms)))
    del_symbol = atoms_prime[del_atom_index].symbol

    # append new atom to system
    del atoms_prime[del_atom_index]

    # get new energy
    delta_energy = atoms_prime.get_potential_energy() - e0
    # get chemical potential
    mu = chem_potentials[del_symbol]
    print '\t\tremoval delta energy', delta_energy
    # print '\t\tremoval exp', np.exp(-1. * beta * delta_energy - beta * mu)
    # calculate acceptance
    if np.random.random() < np.exp(
            min([0, -1. * beta * delta_energy - beta * mu
                 ])) and not np.isnan(delta_energy):
        return atoms_prime
    else:
        return None


class GrandCanonicalEnsemble(Ensemble):
    """
    Grand Canonical Monte Carlo simulation
    >>> from ase.cluster.octahedron import Octahedron
    >>> from pyiid.calc.spring_calc import Spring
    >>> atoms = Octahedron('Au', 3)
    >>> atoms.rattle(.1)
    >>> atoms.center()
    >>> calc = Spring(rt=2.5, k=200)
    >>> atoms.set_calculator(calc)
    >>> gc = GrandCanonicalEnsemble(atoms, {'Au': 0.0}, 3000)
    >>> traj = gc.run(10000)
    """

    def __init__(self, atoms, chemical_potentials, temperature=100,
                 restart=None, logfile=None, trajectory=None, seed=None,
                 verbose=False, resolution=None, voxel_weighting=False):
        Ensemble.__init__(self, atoms, restart, logfile, trajectory, seed,
                          verbose)
        self.beta = 1. / (temperature * kB)
        self.chem_pot = chemical_potentials
        self.metadata = {'rejected_additions': 0, 'accepted_removals': 0,
                         'accepted_additions': 0, 'rejected_removals': 0}
        self.resolution = resolution
        self.voxel_weighting = voxel_weighting

    def step(self):
        if self.random_state.uniform() >= .5:
            mv = 'remove'
            new_atoms = del_atom(self.traj[-1], self.chem_pot, self.beta,
                                 self.random_state
                                 )
        else:
            mv = 'add'
            new_atoms = add_atom(self.traj[-1], self.chem_pot, self.beta,
                                 self.random_state, resolution=self.resolution,
                                 voxel_weighting=self.voxel_weighting
                                 )
        if new_atoms is not None:
            if self.verbose:
                print '\t' + mv + ' atom accepted'
                print '\tCurrent atom count', len(new_atoms)

            if mv == 'add':
                self.metadata['accepted_additions'] += 1
            elif mv == 'remove':
                self.metadata['accepted_removals'] += 1

            self.traj.append(new_atoms)
            return [new_atoms]
        else:
            if self.verbose:
                print '\t' + mv + ' atom rejected'
                print '\tCurrent atom count', len(self.traj[-1])

            if mv == 'add':
                self.metadata['rejected_additions'] += 1
            elif mv == 'remove':
                self.metadata['rejected_removals'] += 1

            return None

    def estimate_simulation_duration(self, atoms, iterations):
        t2 = time()
        e = atoms.get_potential_energy()
        te = time() - t2

        total_time = 0.
        for i in xrange(iterations):
            total_time += te
        return total_time
