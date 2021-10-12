from bs4 import BeautifulSoup
from . import fsmetrics
import pandas as pd
import requests
import re


def make_edgar_request(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.131 Safari/537.36"
    }
    edgar_request = requests.get(url, headers=headers)
    return edgar_request


def convert_filing_to_folder(edgar_filing_url):
    # For all SEC Filings, if you remove the last slug, you can go to the root folder
    base_url = "/".join(edgar_filing_url.replace("ix?doc=/", "").split("/")[:-1])
    filing_summary_url = base_url + "/FilingSummary.xml"
    return base_url, filing_summary_url


def retrieve_face_report_slugs(filing_summary_url):
    filing_summary_soup = BeautifulSoup(
        make_edgar_request(filing_summary_url).text, "lxml"
    )
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

    cash_flow_reports = [
        report
        for report in reports
        if "cash flows" in report.find(tag_for_report_name).text.lower() 
        and
        "parenthetical" not in report.find(tag_for_report_name).text.lower()
    ]
    assert len(cash_flow_reports) == 1, "Cash Flow ambiguous or not found"
    cash_flow_report_slug = cash_flow_reports[0].find(tag_for_file_name).text

    slug_dictionary = dict(
        BS=balance_sheet_report_slug,
        IS=income_statement_report_slug,
        CF=cash_flow_report_slug,
    )

    return slug_dictionary


def extract_dollars(string):
    if "(" in string:
        string = re.sub(r"\((.*)\)", r"-\1", string)
    return string


def clean_dataframe(originalFrame):
    frame = originalFrame.copy()
    if type(frame) == pd.DataFrame:
        for col in frame.columns:
            if frame[col].dtype == "object":
                try:
                    frame[col] = clean_dataframe(
                        frame[col].str.strip().str.replace("-|—", "0", regex=False)
                    )
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
    table_df = pd.read_html(edgar_request.content)[0]

    if type(table_df.columns) == pd.MultiIndex:
        first_level = table_df.columns.get_level_values(0)
        table_df.columns = table_df.columns.droplevel(0)

    duplicate_column_names = any(table_df.columns.duplicated())
    if duplicate_column_names:
        table_df.columns = first_level + "\n" + table_df.columns

    try:
        if " in " in table_df.columns[0]:
            table_multiple = re.findall(r"(in [A-Z][a-z]+)", table_df.columns[0])[0].lower()
        else:
            table_multiple = "in ones"
        print(table_multiple)
        table_multiple_map = {"in ones": 1, "in thousands": 1_000, "in millions": 1_000_000, "in billions": 1_000_000_000}
        table_multiple = table_multiple_map[table_multiple]
    except Exception as e:
        print(f"Error with table multiple: {e}.")
        print(f"Table url: {table_url}")

    table_df = table_df.rename(columns={table_df.columns[0]: "Captions"})
    table_df = table_df.dropna(thresh=len(table_df) * 0.1, axis=1)
    table_df = table_df.pipe(clean_dataframe)

    table_df[table_df.select_dtypes("number").columns] = table_df.select_dtypes("number") * table_multiple

    return table_df


def remove_rows_of_zeros(dataframe):
    return dataframe.loc[~(dataframe.select_dtypes("number") == 0).all(axis=1)]


def common_size_financial_statement(original_dataframe=pd.DataFrame, divisor=None):
    dataframe = original_dataframe.copy()
    numeric_dataframe = dataframe.select_dtypes("number")
    numeric_columns = numeric_dataframe.columns

    if type(divisor) == pd.Series:
        assert len(divisor) == len(
            numeric_columns
        ), "Length of columns does not equal length of divisor"
        assert all(
            divisor.index == numeric_columns
        ), "Dataframe columns does not agree to divisor index"
        divisor = divisor.abs()
    else:
        divisor = abs(divisor)

    dataframe[numeric_columns] = numeric_dataframe.div(divisor)
    return dataframe


def parse_dei_table(base_url):
    request = make_edgar_request(base_url + "/R1.htm")
    doc_and_entity_df = pd.read_html(request.content)[0]
    doc_and_entity_df.columns = doc_and_entity_df.columns.droplevel(0)
    label_column = doc_and_entity_df.columns[0]
    doc_and_entity_df = doc_and_entity_df.set_index(label_column)
    return doc_and_entity_df



class Filing:

    def __init__(self, edgar_filing_url):
        self.base_url, self.filing_summary_url = convert_filing_to_folder(edgar_filing_url=edgar_filing_url)
        self.get_slugs()
        self.ticker = edgar_filing_url.split("/")[-1].split("-")[0]
        self.period_end = edgar_filing_url.split("/")[-1].split("-")[1].replace(".htm", "")


    def get_slugs(self):
        self.slugs = retrieve_face_report_slugs(self.filing_summary_url)
        self.balance_sheet_url = self.base_url + "/" + self.slugs["BS"]
        self.income_statement_url = self.base_url + "/" + self.slugs["IS"]
        self.cash_flow_url = self.base_url + "/" + self.slugs["CF"]


    def get_oustanding_shares(self):
        shares_as_of_date, shares_outstanding = fsmetrics.get_shares_outstanding(self.base_url)
        return shares_as_of_date, shares_outstanding


    def get_balance_sheet(self, commonsize=False):
        if hasattr(self, "bs"):
            bs = self.bs
        else:
            bs = get_clean_table(self.balance_sheet_url)
            bs = bs.pipe(remove_rows_of_zeros)
            self.bs = bs
        
        if commonsize:
            divisor_caption = [caption for caption in bs["Captions"] if re.search(r"total", caption.lower()) and re.search(r"equity", caption.lower())][0]
            bs = common_size_financial_statement(bs, divisor=bs.query("Captions == @divisor_caption").select_dtypes("number").iloc[0])
                
            styled_bs = bs.style\
                        .background_gradient(cmap='Blues', axis=0,)\
                        .set_properties(**{'padding': '10px'})\
                        .format({col: '{:,.2%}'.format for col in bs.select_dtypes("number").columns })

        else:
            styled_bs = bs.style\
                        .background_gradient(cmap='Blues', axis=0,)\
                        .set_properties(**{'padding': '10px'})\
                        .format({col: '{:,.0f}'.format for col in bs.select_dtypes("number").columns })

        return bs, styled_bs


    def get_income_statement(self, commonsize=False):
        if hasattr(self, "is_"):
            is_df = self.is_
        else:
            is_df = get_clean_table(self.income_statement_url)
            is_df = is_df.query("~Captions.fillna('').str.contains('\[')") 
            is_df = is_df.query("Captions.notnull()")
            is_df = is_df.dropna(thresh=len(is_df)*.1, axis=1)
            is_df = is_df.pipe(clean_dataframe)
            is_df = is_df.pipe(remove_rows_of_zeros)
            is_df = is_df.drop_duplicates(subset=["Captions"], keep="first")
            self.is_ = is_df
        
        if commonsize:
            is_df = common_size_financial_statement(is_df, divisor=is_df.select_dtypes("number").iloc[0])
                
            styled_is = is_df.style\
                    .background_gradient(cmap='Blues', axis=0,)\
                    .set_properties(**{'padding': '10px'})\
                    .format({col: '{:,.2%}'.format for col in is_df.select_dtypes("number").columns })

        else:
            styled_is = is_df.style\
                    .background_gradient(cmap='Blues', axis=0,)\
                    .set_properties(**{'padding': '10px'})\
                    .format({col: '{:,.0f}'.format for col in is_df.select_dtypes("number").columns })


        return is_df, styled_is


    def get_cash_flow(self, commonsize=False):
        if hasattr(self, "cf"):
            cf = self.cf
        else:
            cf = get_clean_table(self.cash_flow_url)
            cf = cf.pipe(remove_rows_of_zeros)
            self.cf = cf

        if commonsize:
            cf = common_size_financial_statement(cf, divisor=cf.select_dtypes("number").iloc[0])

            styled_cf = cf.style\
                    .background_gradient(cmap='RdBu', axis=0,)\
                    .set_properties(**{'padding': '10px'})\
                    .format({col: '{:,.2%}'.format for col in cf.select_dtypes("number").columns })

        else:
            styled_cf = cf.style\
                    .background_gradient(cmap='RdBu', axis=0,)\
                    .set_properties(**{'padding': '10px'})\
                    .format({col: '{:,.0f}'.format for col in cf.select_dtypes("number").columns })

        return cf, styled_cf
