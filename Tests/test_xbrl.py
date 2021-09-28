import sys
sys.path.append('../')

from Helpers.XBRL import XBRLReport
import json

with open("./Tests/test_data.json", "r") as test_data:
    test_dictionary = json.load(test_data)
    filing_url = test_dictionary["test_filing_url"]


def test_all_tags_accounted_for():
    xml_soup = XBRLReport.parse_xml_tree( filing_url )
    all_tags = xml_soup.find().find_all(recursive=False)
    tag_dictionary = XBRLReport.retrieve_tags( xml_soup )
    assert len(all_tags) == ( len(tag_dictionary["context_tags"]) + len(tag_dictionary["fact_tags"]) + len(tag_dictionary["unit_tags"]) + len(tag_dictionary["link_tags"]) ),\
        "Length of all tags does not equal to context, fact, unit, and link tags."

