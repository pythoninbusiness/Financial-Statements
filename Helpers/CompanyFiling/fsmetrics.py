import pandas as pd
from . import Filing
import re


def get_shares_outstanding(base_url):
    dei_table = Filing.parse_dei_table(base_url)

    share_multiplier_in_name = re.search(r"(shares in \w+)", dei_table.index.name)
    table_multiple_map = {"in ones": 1, "in thousands": 1_000, "in millions": 1_000_000, "in billions": 1_000_000_000}

    if share_multiplier_in_name:
        multiplier_string = re.findall(r"shares (in [A-Z][a-z]+)", dei_table.index.name)[0].lower()
    else:
        multiplier_string = "in ones"

    multiplier = table_multiple_map[multiplier_string]

    if dei_table.index.str.contains("Shares Outstanding").sum() == 1:
        shares_as_of_date, shares_outstanding = dei_table.loc["Entity Common Stock, Shares Outstanding"].dropna().reset_index().squeeze().values
    else:
        shares_as_of_date, shares_outstanding = dei_table.loc["Entity Common Stock, Shares Outstanding"].iloc[0].dropna().reset_index().values[0]

    shares_outstanding = shares_outstanding * multiplier

    return shares_as_of_date, shares_outstanding


def book_value_per_share(balance_sheet_url, shares_outstanding):
    bs = Filing.get_clean_table(balance_sheet_url)
    bs = bs.pipe(Filing.remove_rows_of_zeros)

    total_equity_regex = r"([Total]*\s*[stockholders\W*]*[shareholders\W*]*[eE]quity)$"
    equity_line_item = bs[bs["Captions"].str.match(total_equity_regex)]
    if len(equity_line_item) > 1:
        total_equity = equity_line_item.iloc[0].values[1]
    else:
        total_equity = equity_line_item.squeeze().values[1]

    return total_equity / shares_outstanding


def cash_flow_per_share(cash_flow_url, shares_outstanding, per_share=True):
    cf = Filing.get_clean_table(cash_flow_url)
    cf = cf.pipe(Filing.remove_rows_of_zeros)

    operating_activity_caption = [ caption for caption in cf["Captions"] if "operating activities" in caption.lower() and "net cash" in caption.lower()]
    assert len(operating_activity_caption) == 1, "Number of operating activity captions should be only one for net operating activity"
    operating_activity_values = cf.set_index("Captions").loc[operating_activity_caption].squeeze().values

    # Companies sometimes report previous QTD values as well. These will always have the net activity items be equal to zero.
    if operating_activity_values[0] != 0:
        operating_activity_value = operating_activity_values[0]
    else:
        if len(operating_activity_values) == 3:
            operating_activity_value = operating_activity_values[1]
        else:
            operating_activity_value = [value for value in operating_activity_values if value != 0][0]

    overall_cash_flow_caption = [ caption for caption in cf["Captions"] if re.search(r"increase|decrease", caption.lower()) and "cash" in caption.lower()]
    overall_cash_flow_values = cf.set_index("Captions").loc[overall_cash_flow_caption].squeeze().values

    if overall_cash_flow_values[0] != 0:
        overall_cash_flow_value = overall_cash_flow_values[0]
    else:
        if len(overall_cash_flow_values) == 3:
            overall_cash_flow_value = overall_cash_flow_values[1]
        else:
            overall_cash_flow_value = [value for value in overall_cash_flow_values if value != 0][0]

    overall_operating_activity_per_share = operating_activity_value / shares_outstanding
    overall_cash_flow_per_share = overall_cash_flow_value / shares_outstanding

    if per_share:
        return overall_operating_activity_per_share, overall_cash_flow_per_share
    else:
        return operating_activity_value, overall_cash_flow_value