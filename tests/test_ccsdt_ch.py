"""CCSDT computation on open-shell CH molecule."""

from pathlib import Path
import numpy as np
from ccpy.drivers.driver import Driver

TEST_DATA_DIR = str(Path(__file__).parent.absolute() / "data")

def test_ccsdt_ch():
    driver = Driver.from_gamess(
        logfile=TEST_DATA_DIR + "/ch/ch.log",
        fcidump=TEST_DATA_DIR + "/ch/ch.FCIDUMP",
        nfrozen=1,
    )
    driver.system.print_info()

    driver.run_cc(method="ccsdt")

    # Check reference energy
    assert np.allclose(driver.system.reference_energy, -38.2713247488)
    # Check CCSDT energy
    assert np.allclose(driver.correlation_energy, -0.1164237849)
    assert np.allclose(
        driver.system.reference_energy + driver.correlation_energy, -38.3877485336
    )

if __name__ == "__main__":
    test_ccsdt_ch()