import requests
from datetime import datetime

def sendCoralogix(private_key, logs, app_name, subsystem_name, severity, computer_name=None, class_name=None, category=None, method_name = None):
    """
    This function sends a request to Coralogix with the given data.
    private_key: Coralogix account private key, as String.
    logs: the logs text, as String.
    app_name: Application Name to be shown in Coralogix, as String.
    subsystem_name: Subsystem Name to be shown in Coralogix, as String.
    severity: Severity of the logs as String. Values: 1 – Debug, 2 – Verbose, 3 – Info, 4 – Warn, 5 – Error, 6 – Critical
    computer_name: Computer Name to be shown in Coralogix, as String.
    class_name: Class Name to be shown in Coralogix, as String.
    category: Category to be shown in Coralogix, as String.
    method_name: Method Name to be shown in Coralogix, as String.
    """


    url = "https://api.coralogix.com/api/v1/logs"
    #Get the datetime and change it to miliseconds
    now = datetime.now()
    
    data = {
            "privateKey": private_key, 
            "applicationName": app_name,
            "subsystemName": subsystem_name,
            "logEntries": [
                {
                "timestamp": now.timestamp()*1000,   #1457827957703.342, 
                "text": logs,
                "severity": severity
                }
            ]
        }
    if computer_name :
        data["computerName"] = computer_name 
    if class_name:
        data["logEntries"][0]["className"] = class_name
    if category:
        data["logEntries"][0]["category"] = category
    if method_name:
        data["logEntries"][0]["methodName"] = method_name

    #Make the request to coralogix
    requests.post(url, json=data)

    return True

#sendCoralogix("ad0e94ce-b59d-8e11-e3f7-93f825222407","{'data':'Test'}", "Library_Test", "Library_Test" )
