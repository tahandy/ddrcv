"""Run the focused regression suites with all temporary artifacts in this tree."""
import argparse
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model',help='Enable the offline real-model tests')
    parser.add_argument('--video',help='Enable the MKV crop test with --model')
    args=parser.parse_args()
    os.chdir(ROOT)
    temporary=ROOT/'.workbench/test-tmp';temporary.mkdir(parents=True,exist_ok=True)
    tempfile.tempdir=str(temporary)
    os.environ.update(TEMP=str(temporary),TMP=str(temporary),MPLCONFIGDIR=str(ROOT/'.workbench/matplotlib'))
    if args.model:os.environ['DDRCV_TEST_OCR_MODEL']=str(Path(args.model).resolve())
    if args.video:os.environ['DDRCV_RESULTS_VIDEO']=str(Path(args.video).resolve())
    patterns=('test_results*.py','test_tournament*.py','test_rapidocr.py','test_workbench.py','test_monitored_regions.py')
    suite=unittest.TestSuite(unittest.defaultTestLoader.discover('tests',pattern=pattern) for pattern in patterns)
    result=unittest.TextTestRunner(verbosity=1).run(suite)
    raise SystemExit(not result.wasSuccessful())

if __name__=='__main__':main()
