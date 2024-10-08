"""This module provides functions to check the equivalence of two circuits using Grover's algorithm."""

from __future__ import annotations

import string
from operator import itemgetter
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
from qiskit import QuantumCircuit
from qiskit.circuit.library import GroverOperator, PhaseOracle
from qiskit.compiler import transpile
from qiskit_aer import AerSimulator

if TYPE_CHECKING:
    from pathlib import Path


def create_condition_string(num_bits: int, num_counter_examples: int) -> tuple[str, list[str]]:
    """Creates a synthetic miter string with multiple variables in form of letters.

    These represent the input bits of to be verified circuits and can be either 0 or 1.
    The function also returns the corresponding counter examples to the miter string, that is, the bitstrings that satisfy the miter condition.
    A miter can be of the form "a & b & c & d" where a, b, c, d are input bits. The counter examples are the bitstrings that satisfy the miter condition, e.g. "0000" for the miter "a & b & c & d".

    Parameters
    ----------
    num_bits : int
        Number of input bits
    num_counter_examples : int
        Number of counter examples

    Returns:
    -------
    res_string : str
        Resulting condition string
    counter_examples : list[str]
        The corresponding bitstrings to res_string (e.g. counter_examples is ['1111'] for res_string 'a & b & c & d')
    """
    if num_bits < 0 or num_counter_examples < 0:
        msg = "The number of bits or counter examples cannot be used."
        raise ValueError(msg)

    alphabet = list(string.ascii_lowercase)
    counter_examples: list[str] = []
    if (
        num_counter_examples == 0
    ):  # Since the qiskit PhaseOracle does not support empty conditions, we need to add a condition that is always false
        res, _ = create_condition_string(num_bits, 1)  # returns e.g. "~a & ~b & ~c & ~d" for num_bits = 4
        res += " & a"  # turns the miter into "~a & ~b & ~c & ~d & a" which is always false
        return res, counter_examples
    res_string: str = ""
    counter_examples = []
    for num in range(num_counter_examples):
        bitstring = list(str(format(num, f"0{num_bits}b")))[
            ::-1
        ]  # e.g. ['0', '0', '0', '0'] for num = 0 and num_bits = 4
        counter_examples.append(str(format(num, f"0{num_bits}b")))  # appends ['0000'] for num = 0 and num_bits = 4
        # The following lines add a negated letter (e.g. "~a") for each "0" and a letter (e.g. "a") for each "1" in the bitstring list.
        # If the first letter is added (so i > 0), the subsequent letters are added together with a logical AND operator (e.g. "~a & ~b & ~c & ~d").
        for i, char in enumerate(bitstring):
            if char == "0" and i == 0:
                bitstring[i] = "~" + alphabet[i]
            elif char == "1" and i == 0:
                bitstring[i] = alphabet[i]
            elif char == "0":
                bitstring[i] = " & " + "~" + alphabet[i]
            elif char == "1":
                bitstring[i] = " & " + alphabet[i]
        combined_bitstring = "".join(bitstring)
        if num < num_counter_examples - 1:
            res_string += combined_bitstring + " | "
        else:
            res_string += combined_bitstring
    return res_string, counter_examples


def find_counter_examples(
    miter: str,
    num_bits: int,
    shots: int,
    delta: float,
    counter_examples: list[str] | None = None,
) -> list[str] | int | None:
    """Runs our approach utilizing Grover's algorithm to find counter examples for a given miter.

    The function is also used in the "try_parameter_combinations" function to test different parameter combinations of our approach.
    In this case, a synthetic miter is used for which the counter examples are known and one can check, if for given parameters (such as shots and delta)
    our approach can find the correct counter examples.

    Parameters
    ----------
    miter : str
        Miter condition string
    num_bits : int
        Number of input bits
    shots : int
        Number of shots to run the quantum circuit for
    delta : float
        Threshold for the stopping condition
    counter_examples : list[str] | NoneType
        List of counter examples

    Returns:
    -------
    Found counter examples for a given miter (counter_examples=None) or the number of iterations to find the counter examples (or "-" if no/wrong counter examples were found) if the counter examples are known beforehand.
    """
    if not 0 <= delta <= 1:
        msg = f"Invalid value for delta {delta}, which must be between 0 and 1."
        raise ValueError(msg)

    total_num_combinations = 2**num_bits
    start_iterations = np.floor(np.pi / (4 * np.arcsin((1 / total_num_combinations) ** 0.5)) - 0.5).astype(int)

    simulator = AerSimulator(method="statevector")

    total_iterations = 0
    for iterations in reversed(range(1, start_iterations + 1)):
        total_iterations += iterations
        oracle = PhaseOracle(miter)

        operator = GroverOperator(oracle).decompose()
        num_bits = operator.num_qubits
        total_num_combinations = 2**num_bits

        qc = QuantumCircuit(num_bits)
        qc.h(list(range(num_bits)))
        qc.compose(operator.power(iterations).decompose(), inplace=True)
        qc.measure_all()

        qc = transpile(qc, simulator)

        job = simulator.run(qc, shots=shots)
        result = job.result()
        counts_dict = dict(result.get_counts())
        counts_list = list(counts_dict.values())
        counts_list.sort(reverse=True)

        counts_dict = dict(
            sorted(counts_dict.items(), key=itemgetter(1))[::-1]
        )  # Sort state dictionary with respect to values (counts)

        found_counter_examples = []
        for i in range(int(total_num_combinations * 0.5)):
            if (i + 1) == len(counts_list):
                found_counter_examples_list = counts_list
                found_counter_examples_dict = {
                    list(counts_dict.keys())[t]: list(counts_dict.values())[t]
                    for t in range(len(found_counter_examples_list))
                }
                found_counter_examples = list(found_counter_examples_dict.keys())
                break

            diff = counts_list[i] - counts_list[i + 1]
            if diff > counts_list[i] * delta:
                found_counter_examples_list = counts_list[: i + 1]
                found_counter_examples_dict = {
                    list(counts_dict.keys())[t]: list(counts_dict.values())[t]
                    for t in range(len(found_counter_examples_list))
                }
                found_counter_examples = list(found_counter_examples_dict.keys())
                break

    if counter_examples is None:
        return found_counter_examples

    if sorted(found_counter_examples) == sorted(counter_examples):
        return total_iterations

    return None


def try_parameter_combinations(
    path: Path,
    range_deltas: list[float],
    range_num_bits: list[int],
    range_fraction_counter_examples: list[float],
    shots_factor: float,
    num_runs: int,
    verbose: bool = False,
) -> None:
    """Tries different parameter combinations for Grover's algorithm to find the optimal parameters.

    Parameters
    ----------
    path : str
        Path to save the results
    range_deltas : list[float]
        List of delta values to try
    range_num_bits : list[int]
        List of numbers of input bits to try
    range_fraction_counter_examples : list[float]
        List of fractions of counter examples to try
    shots_factor : float
        Factor to scale the number of shots with the number of input bits (shots_factor * 2^num_bits)
    num_runs : int
        Number of runs for each parameter combination
    verbose : bool
        If True, print the current parameter combination

    """
    data = pd.DataFrame(columns=["Input Bits", "Counter Examples", *range_deltas])
    i = 0
    for num_bits in range_num_bits:
        for fraction_counter_examples in range_fraction_counter_examples:
            num_counter_examples = round(fraction_counter_examples * 2**num_bits)
            row: list[float | int | str] = [num_bits, num_counter_examples]
            for delta in range_deltas:
                if verbose:
                    print(
                        f"num_bits: {num_bits}, fraction_counter_examples: {fraction_counter_examples}, delta: {delta}"
                    )
                results = []
                for _run in range(num_runs):
                    miter, counter_examples = create_condition_string(num_bits, num_counter_examples)
                    result = find_counter_examples(
                        miter=miter,
                        num_bits=num_bits,
                        shots=shots_factor * (2**num_bits),
                        delta=delta,
                        counter_examples=counter_examples,
                    )
                    results.append(result)
                if None in results:
                    row.append("-")
                else:
                    row.append(float(np.mean(np.asarray(results))))
            data.loc[i] = row
            i += 1

    data.to_csv(path, index=False)
