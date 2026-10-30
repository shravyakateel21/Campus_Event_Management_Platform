import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SIGNATURE_DIR = os.path.join(BASE_DIR, "static", "signatures")
DEFAULT_DEPARTMENT = "MCA"

# Signs every certificate (left side), whatever the department.
PRINCIPAL = {
    "name": "Dr Ashok Kumar T",        # TODO: put the real name
    "title": "Principal",
    "signature": "principal.jpeg",         # save in static/signatures/
}

DEPARTMENTS = {
    "MCA": {
        "name": "MCA",
        "hod_name": "Dr Bruce Mathew",
        "hod_title": "Head- MCA",
        "hod_signature": "MCA_hod.png",
    },
    "CSE": {
        "name": "Computer Science & Engineering",
        "hod_name": "Dr Antony P J",
        "hod_title": "Head- CSE",
        "hod_signature": "CSE_hod.jpeg",
    },
    "ISE": {
        "name": "Information Science & Engineering",
        "hod_name": "Dr John Prakash Veigas",
        "hod_title": "Head- ISE",
        "hod_signature": "ISE_hod.jpeg",
    },
    "ECE": {
        "name": "Electronics & Communication Engineering",
        "hod_name": "Dr Kiran Kumar V G",
        "hod_title": "Head- ECE",
        "hod_signature": "ECE_hod.jpeg",
    },
    "ME": {
        "name": "Mechanical Engineering",
        "hod_name": "Dr Rajesh Rai P",
        "hod_title": "Head- ME",
        "hod_signature": "ME_hod.jpeg",
    },
    "CV": {
        "name": "Civil Engineering",
        "hod_name": "Dr Suman Kundapura",
        "hod_title": "Head- CV",
        "hod_signature": "CV_hod.jpeg",
    },
    "MBA": {
        "name": "Master of Business Administration",
        "hod_name": "Dr Prameela S Shetty",
        "hod_title": "Head- MBA",
        "hod_signature": "MBA_hod.jpeg",
    }
}


def resolve(event_department=None, organizer_department=None):
    for raw in (event_department, organizer_department):
        key = (raw or "").strip().upper()
        if not key:
            continue
        if key in DEPARTMENTS:
            return key, DEPARTMENTS[key]
        for code, info in DEPARTMENTS.items():
            if info["name"].upper() == key:
                return code, info
    return DEFAULT_DEPARTMENT, DEPARTMENTS[DEFAULT_DEPARTMENT]



def signature_path(filename):
    if not filename:
        return None
    path = os.path.join(SIGNATURE_DIR, filename)
    return path if os.path.exists(path) else None