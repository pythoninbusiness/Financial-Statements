from bs4 import BeautifulSoup
import pandas as pd
import requests
import re


def make_edgar_request(url):
    headers = {"User-Agent" : "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.131 Safari/537.36"}
    edgar_request = requests.get(url, headers=headers)
    return edgar_request


def convert_filing_to_folder(edgar_filing_url):
    # For all SEC Filings, if you remove the last slug, you can go to the root folder 
    base_url = "/".join( edgar_filing_url.replace("ix?doc=/", "").split("/")[:-1] )
    filing_summary_url = base_url + "/FilingSummary.xml"
    return base_url, filing_summary_url
    
    
def retrieve_face_report_slugs(filing_summary_url):
    filing_summary_soup = BeautifulSoup(make_edgar_request(filing_summary_url).text, 'lxml')
    reports = filing_summary_soup.find_all("report")

    tag_for_report_name = "shortname"
    tag_for_file_name = "htmlfilename"

    # Income Statement and Balance Sheet are second and fourth reports
    if re.search(r"balance", reports[2].find(tag_for_report_name).text.lower()):
        balance_sheet_report_slug = reports[1].find(tag_for_file_name).text
        income_statement_report_slug = reports[3].find(tag_for_file_name).text
    else:
        income_statement_report_slug = reports[1].find(tag_for_file_name).text
        balance_sheet_report_slug = reports[3].find(tag_for_file_name).text

    cash_flow_reports = [report for report in reports if "cash flows" in report.find(tag_for_report_name).text.lower()]
    assert len(cash_flow_reports) == 1, "Cash Flow ambiguous or not found"
    cash_flow_report_slug = cash_flow_reports[0].find(tag_for_file_name).text
    
    slug_dictionary = dict(BS=balance_sheet_report_slug, IS=income_statement_report_slug, CF=cash_flow_report_slug)

    return slug_dictionary


def extract_dollars(string):
        if "(" in string:
                string = re.sub(r"\((.*)\)", r"-\1", string)
        return string


def clean_dataframe(originalFrame):
    frame = originalFrame.copy()
    if type(frame) == pd.DataFrame:
        for col in frame.columns:
            if frame[col].dtype == 'object':
                try:
                        frame[col] = clean_dataframe(frame[col].str.strip().str.replace("-|—", "0", regex=False))
                except:
                        print(f"Unable to clean column - {col}.")
        return frame

    elif type(frame) == pd.Series:
        frame = frame.str.strip().fillna("0")
        frame[frame == "—"] = "0"
        frame = frame.apply(lambda x: re.sub(r"\$|,", "", str(x)))
        frame = frame.apply(extract_dollars)
        
        return pd.to_numeric(frame)


def get_clean_table(table_url):
    edgar_request = make_edgar_request(table_url)
    list_of_tables = pd.read_html(edgar_request.content)
    table_df = list_of_tables[0]

    if type(table_df.columns) == pd.MultiIndex:
        first_level = table_df.columns.get_level_values(0)
        table_df.columns = table_df.columns.droplevel(0) 

    duplicate_column_names = any(table_df.columns.duplicated())
    if duplicate_column_names:
        table_df.columns = first_level + "\n" + table_df.columns

    table_df = table_df.rename(columns={table_df.columns[0]: "Captions"})
    table_df = table_df.dropna(thresh=len(table_df)*.1, axis=1)
    table_df = table_df.pipe(clean_dataframe)
    return table_df


def remove_rows_of_zeros(dataframe):
    return dataframe.loc[ ~(dataframe.select_dtypes('number') == 0).all(axis=1) ]


def common_size_financial_statement(dataframe=pd.DataFrame, divisor=None):
    numeric_dataframe = dataframe.select_dtypes("number")
    numeric_columns = numeric_dataframe.columns

    if type(divisor) == pd.Series:
        assert len(divisor) == len(numeric_columns), "Length of columns does not equal length of divisor"
        assert all(divisor.index == numeric_columns), "Dataframe columns does not agree to divisor index"
        divisor = divisor.abs()
    else:
        divisor = abs(divisor)
 
    dataframe[numeric_columns] = numeric_dataframe.div(divisor)
    return dataframe
