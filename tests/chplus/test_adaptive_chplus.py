from pathlib import Path
import numpy as np
from ccpy.drivers.driver import Driver
from ccpy.drivers.adaptive import AdaptEOMDriver

TEST_DATA_DIR = str(Path(__file__).parents[1].absolute() / "data")

def test_adaptive_chplus():
    driver = Driver.from_gamess(
        logfile=TEST_DATA_DIR + "/chplus/chplus.log",
        fcidump=TEST_DATA_DIR + "/chplus/chplus.FCIDUMP",
        nfrozen=0,
    )
    driver.system.print_info()

    driver.options["maximum_iterations"] = 500
    state_index=4
    state_irrep="A1"
    roots_per_irrep={"A1": 4}
    multiplicity = 1
    adaptdriver = AdaptEOMDriver(driver, state_index, state_irrep, roots_per_irrep, multiplicity, 
                                 nacto=3, nactu=3, 
                                 percentage=[0.0, 1.0, 2.0, 3.0, 4.0, 5.0])

    adaptdriver.run()

if __name__ == "__main__":
    test_adaptive_chplus()
