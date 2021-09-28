import sys
sys.path.append('../')

from Helpers.CompanyFiling import Filing
import json

with open("./Tests/test_data.json", "r") as test_data:
    test_dictionary = json.load(test_data)
    filing_url = test_dictionary["test_filing_url"]


def test_edgar_request_works():
    request_status_code = Filing.make_edgar_request( filing_url ).status_code
    assert request_status_code == 200, "Request code should be 200; if other (e.g., 403) then may need to adjust headers"


def test_filing_summary():
    base_url, filing_summary_url = Filing.convert_filing_to_folder( filing_url )
    request_status_code = Filing.make_edgar_request( filing_summary_url ).status_code
    assert request_status_code != 404, "Filing does not have a FilingSummary.xml file"

