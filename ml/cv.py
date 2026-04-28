from sklearn.model_selection import TimeSeriesSplit

def ts_splits(n_splits=5):
    return TimeSeriesSplit(n_splits=n_splits)

