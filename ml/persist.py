import mlflow

def log_model(model, name):
    mlflow.sklearn.log_model(model, name)

