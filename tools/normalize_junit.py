"""Frappe 16 appends one XML document per test cohort; combine for CI readers."""
import argparse
from pathlib import Path
import re
from xml.etree import ElementTree as ET

parser=argparse.ArgumentParser()
parser.add_argument("source")
parser.add_argument("destination")
args=parser.parse_args()
parts=[part.strip() for part in re.split(r"<\?xml[^>]+>\s*",Path(args.source).read_text(encoding="utf-8")) if part.strip()]
root=ET.Element("testsuites")
for part in parts:
    parsed=ET.fromstring(part)
    if parsed.tag=="testsuite":
        root.append(parsed)
    elif parsed.tag=="testsuites":
        root.extend(parsed)
    else:
        raise ValueError("Unexpected test report root")
tests=len(root.findall(".//testcase"))
failures=len(root.findall(".//failure"))
errors=len(root.findall(".//error"))
root.set("tests",str(tests))
root.set("failures",str(failures))
root.set("errors",str(errors))
ET.indent(root)
ET.ElementTree(root).write(args.destination,encoding="utf-8",xml_declaration=True)
print(f"JUnit: {tests} tests, {failures} failures, {errors} errors; {len(parts)} source cohorts")
