from bs4 import BeautifulSoup
import pandas as pd
import requests
 

def make_edgar_request(url):
    headers = {"User-Agent" : "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.131 Safari/537.36"}
    edgar_request = requests.get(url, headers=headers)
    return edgar_request


def parse_xml_tree(filing_url):
    """
    Purpose: Take an Edgar Filing and covert it into the XML url. Parse the url and return the BeautifulSoup object.
    Inputs: Edgar Filing URL (iXBRL or HTML will work).
    Output: BeautifulSoup object.
    """

    xml_url = filing_url.replace("ix?doc=/", "").replace(".htm", "_htm.xml")

    edgar_request = make_edgar_request(xml_url)
    soup = BeautifulSoup(edgar_request.text, 'xml')
    return soup


def extract_context_tag_info(context_tag):
    """
    Purpose: Each XBRL filing contains a lot of facts tags. It seems that instead of adding all of the context (i.e., dimensions and axis) attributes
    to each tag, in an effort to save space, Edgar puts all of the unique context combinations in a separate tag. Each fact tag will have a unique context 
    reference that will match one context tag id. The context tag will contain all the dimensions and dates associated with that fact tag. 
    Inputs: List of context tags.
    Output: Dictionary of uids, dates, and dimensions. Can convert to dataframe to merge on the uid column.
    """
    uid = context_tag["id"]

    if context_tag.find("instant"):
        instant_date_year_month_day = context_tag.find("instant").text.split("-")
        date = f"{instant_date_year_month_day[1]}/{instant_date_year_month_day[2]}/{instant_date_year_month_day[0]}"
    else:
        start_date_year_month_day = context_tag.find("startDate").text.split("-")
        end_date_year_month_day = context_tag.find("endDate").text.split("-")
        start_date = f"{start_date_year_month_day[1]}/{start_date_year_month_day[2]}/{start_date_year_month_day[0]}"
        end_date = f"{end_date_year_month_day[1]}/{end_date_year_month_day[2]}/{end_date_year_month_day[0]}"
        date = f"{start_date} to {end_date}"

    explicit_members = context_tag.find_all("explicitMember")
    dimensions = "\n".join( [f"{explicit_member['dimension']} [{explicit_member.text}]" for explicit_member in explicit_members] )

    return dict(uid=uid, date=date, dimensions=dimensions)


def retrieve_tags(xml_soup):
    """
    Purpose: Retrieve all of the context, fact, unit and link tags in the xml soup. We perform a check to ensure that the length of 
    all our extracted tags adds up to the total amount of tags in the xml filing. 
    Inputs: xml soup.
    Output: a dictionary containing all of the tags.
    """
    all_tags = xml_soup.find().find_all(recursive=False)

    context_tags = [tag for tag in all_tags if tag.name == "context"]
    fact_tags = [tag for tag in all_tags if "contextRef" in tag.attrs]
    unit_tags = [tag for tag in all_tags if tag.name == "unit" ]
    link_tags = [tag for tag in all_tags if tag.name == "schemaRef"]

    if len(all_tags) - ( len(context_tags) + len(fact_tags) + len(unit_tags) + len(link_tags) ) != 0:
        print("Script may have additional tags outside of Link, Context, Unit, and Fact tags.")

    return dict(context_tags=context_tags, fact_tags=fact_tags, unit_tags=unit_tags, link_tags=link_tags)


def merge_facts_and_context(tag_dictionary):
    """
    Purpose: Merge the facts and context tags such that each fact will now include the dimensions and dates.
    Inputs: a dictionary containing fact_tags and context_tags.
    Output: a dataframe where each row is a concept with the following attributes: name, value, date, dimensions (and columns to identify which report it came from).
    """
    context_df = pd.DataFrame(map(extract_context_tag_info, tag_dictionary["context_tags"]))
    fact_tag_details = [dict(name=tag.name, context=tag["contextRef"], value=tag.text) for tag in tag_dictionary["fact_tags"]]
    facts_df = pd.DataFrame(fact_tag_details)
    facts_df = facts_df.merge(context_df, left_on="context", right_on="uid", how="left").drop(columns="uid")

    facts_df.loc[:, "Quarter"] = facts_df.query("name == 'DocumentFiscalPeriodFocus' ").value.squeeze()
    facts_df.loc[:, "Year"] = facts_df.query("name == 'DocumentFiscalYearFocus' ").value.squeeze()
    facts_df.loc[:, "Amended"] = facts_df.query("name == 'AmendmentFlag' ").value.squeeze()

    facts_df.loc[:, "Ticker"] = tag_dictionary["link_tags"][0].get('xlink:href').split("-")[0].upper()

    return facts_df


def check_for_mismatches(complete_df):
    """
    Purpose: This is primarily to help check for small presentation differences between periods. For example, if a concept was reported rounded to zero decimals in the prior year but 
    was reported to the thousandth in the current report. This will also catch all facts that have been restated due to reclassifications. 
    Inputs: a dataframe consisting of concepts with date and dimension attributes. 
    Output: a dataframe containing all concepts with the same dimensions and date that have values reported in a previous filing that have either been restated or simply don't agree. 
    """
    mismatch_df = complete_df.drop_duplicates(subset=["name", "dimensions", "date", "value"], keep=False)       # Drop all duplicates where concept, date and value are the same - since that's how it should be
    mismatch_df = mismatch_df[mismatch_df.duplicated(subset=["name", "dimensions", "date"], keep=False)]        # Only return facts where duplicates exist but values don't agree
    mismatch_df = mismatch_df.sort_values(["name", "dimensions", "date"])
    return mismatch_df


class XBRLReport:

    """
    XBRL Report Class\n
    This will instantiate an object that takes in an edgar filing url. This will also make it easy to add additional reports to compare against.

    Use:\n
    report = XBRL.XBRLReport(filing_url)
    report.load_first_report()
    """

    def __init__(self, filing_url):
        self.initial_filing_url = filing_url
        self.all_links = list()
        self.load_first_report()


    def load_first_report(self):
        self.all_links.append(self.initial_filing_url)
        soup = parse_xml_tree(self.initial_filing_url)
        self.tag_dictionary = retrieve_tags(soup)
        self.facts_df = merge_facts_and_context(self.tag_dictionary)
        print("Initial report successfully loaded!")


    def append_report(self, additional_filing_link):
        self.all_links.append(additional_filing_link)
        soup = parse_xml_tree(additional_filing_link)
        additional_facts_df = merge_facts_and_context( retrieve_tags(soup) )
        self.facts_df = pd.concat( [self.facts_df, additional_facts_df] )
        print("Additional report successfully appended!")


    def mismatches(self):
        return check_for_mismatches(self.facts_df)