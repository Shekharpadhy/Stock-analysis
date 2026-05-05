import shap

def explain(model, X):
    return shap.TreeExplainer(model).shap_values(X)

