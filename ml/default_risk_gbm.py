from sklearn.ensemble import GradientBoostingClassifier

def build_model():
    return GradientBoostingClassifier(n_estimators=200, max_depth=4)

