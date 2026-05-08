import pandas as pd

def engineer_credit_features(df: pd.DataFrame) -> pd.DataFrame:
    df['debt_to_equity'] = df['total_debt'] / df['equity']
    df['interest_coverage'] = df['ebit'] / df['interest_expense']
    return df


def fillna_features(df):
    return df.fillna(0)

