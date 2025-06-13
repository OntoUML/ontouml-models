from git import Repo, GitCommandError
from pathlib import Path
from rdflib import Graph, BNode, URIRef, Namespace, Literal
from rdflib.namespace import XSD
from rdflib.namespace import RDF
import random
import string
import re
import requests
import os
import sys

#Configuration
FDP_EMAIL = 's.zaharie@student.utwente.nl'
FDP_PASSWORD = 'admin'
MODELS_DIR = 'models'
METADATA_FILENAME = 'metadata.ttl'
UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$') #compiled regex
CATALOG_URI = "https://w3id.org/ontouml-models/catalog/b663ca18-8085-44a7-bcfe-2c2b5ba1faa8" # files that were not uploaded to FDP don't have the link to the catalog
DCTERMS     = Namespace("http://purl.org/dc/terms/")

#loads the ttl, creates a graph and takes the first subject node which should be the id
def get_subject(file_path: Path):
    g = Graph()
    g.parse(str(file_path), format='turtle')

    DCAT = Namespace("http://www.w3.org/ns/dcat#")
    # Goes through all subjects that have specified predicate and object, assuming one dcat:Dataset at the top
    for s in g.subjects(RDF.type, DCAT.Dataset): # (predicate, object)
        return s

    # goes through the whole graph and just takes the first subject, in case no dcat is found
    for s in g.subjects():
        return s

    return None

# injects the catalog uri into the temporary metadata.ttl file
def inject_parent(file_path: Path, subject):
    g = Graph()
    g.parse(str(file_path), format="turtle")
    g.add((subject, DCTERMS.isPartOf, URIRef(CATALOG_URI))) # inserting the catalog triple
    g.serialize(destination=str(file_path), format="turtle") # overwrite the original file with the complete one

# checks if the id is permanent by checking if last segment is matching with UUID_RE defined in the configuration
# returns true if id is permanent, false otherwise
def is_permanent(subject) -> bool:
    if isinstance(subject, BNode): # checks if its temporary (BNode)
        return False
    if isinstance(subject, URIRef): # checks if its permanent (URIRef)
        # take last segment take last segment of link
        last = str(subject).rstrip('/').rsplit('/', 1)[-1]
        return bool(UUID_RE.match(last))
    return False

# log in to fdp 
def login():
    url = "http://localhost:81/tokens"
    payload = {"email": FDP_EMAIL, "password": FDP_PASSWORD}
    resp = requests.post(url, json=payload)
    if not resp.ok:
        print(f"Login failed: {resp.status_code} {resp.text}", file=sys.stderr)
        sys.exit(1) # exit the script to prevent further calls to the server
    return resp.json().get("token")

# prepatch ttl with catalog, keyword mediatype and isComplete (required by SHACL)
# POST to FDP. If succesful, write back file with permanent id and stage
def getNewId(file_path: str, git, token: str):
    # create graph and populate with triples
    path = Path(file_path)
    g = Graph()
    g.parse(str(path), format="turtle")

    # namespaces
    DCTERMS = Namespace("http://purl.org/dc/terms/")
    DCAT    = Namespace("http://www.w3.org/ns/dcat#")
    OCMV    = Namespace("https://w3id.org/ontouml-models/vocabulary#")
    RDF     = Namespace("http://www.w3.org/1999/02/22-rdf-syntax-ns#")

    # gets the URI of the dataset
    subject = get_subject(path)
    if subject is None:
        raise RuntimeError("No subject in TTL")

    # license is a requirement of the api so we add a default license
    DEFAULT_LICENSE = URIRef("https://creativecommons.org/licenses/by-sa/4.0/")
    # only add if missing
    if (subject, DCTERMS.license, None) not in g:
        g.add((subject, DCTERMS.license, DEFAULT_LICENSE))

    # add reference to the catalog the dataset belongs to, duplicates are harmless
    g.add((subject, DCTERMS.isPartOf, URIRef(CATALOG_URI)))
    # keyword (folder name)
    default_kw = path.parent.name
    g.set((subject, DCAT.keyword, Literal(default_kw, lang="en")))

    # SHACL requires exactly one IANA Turtle media type, so we set it (we override invalid/extra values)
    for dist in g.subjects(RDF.type, DCAT.Distribution):
        # mediaType is text/turtle
        g.set((dist,
               DCAT.mediaType,
               URIRef("https://www.iana.org/assignments/media-types/text/turtle")))
        # SHACL requires every distribution to have  comv:isCompleter true so we set it
        g.set((dist,
               OCMV.isComplete,
               Literal(True, datatype=XSD.boolean)))

    # write out the fully patched TTL & stage to git
    g.serialize(destination=str(path), format="turtle")
    git.add(str(path))

    # send POST request to FDP including token, so server knows we're authenticated
    ttl = path.read_text(encoding="utf-8") #read ttl back into string 
    resp = requests.post(
        "http://localhost:81/model",
        data=ttl,
        headers={
            "Content-Type":  "text/turtle",
            "Accept":        "text/turtle",
            "Authorization": f"Bearer {token}"
        }
    )

    # token expired mid run
    if resp.status_code == 403:
        raise RuntimeError("AUTH_EXPIRED")

    if resp.status_code != 201:
        # shouldn't happen casue we prepatched everything and meet requirements of SHACL
        raise RuntimeError(f"{resp.status_code}: {resp.text}")

    # is success, we add the permanent id files to git and stage
    path.write_text(resp.text, encoding="utf-8")
    git.add(str(path))
    print(f"   ✓ Synced {file_path}")



def main():
    # open repo and checkout master
    repo = Repo(".", search_parent_directories=True)
    git = repo.git
    git.checkout("master")

    # create feature branch and switch to it
    branch_name = "fdp-sync__" + "".join(random.choices(string.ascii_letters + string.digits, k=16))
    repo.create_head(branch_name).checkout()
    print(f"Working on branch: {branch_name}")

    # go through all models, respectively all metadata.ttl files and find the ones with temporary id's
    repo_root = Path(repo.working_tree_dir)
    to_upload = []
    for meta in repo_root.glob(f"{MODELS_DIR}/*/{METADATA_FILENAME}"):
        subject = get_subject(meta)
        if subject is None:
            continue
        if not is_permanent(subject):
            to_upload.append(meta)

    # all models have permanent ids
    if not to_upload:
        print(" All models already have permanent IDs; nothing to do.")
        return

    # print all models with temporary ids
    print("Models to sync:")
    for p in to_upload:
        print("  ", p)

    # log in to fdp
    token = login()
    print(" Logged in to FDP")

    # upload each file
    for meta in to_upload:
        try:
            getNewId(str(meta), git, token) # does all the prepatching
            print(f"   Synced {meta}")
        except RuntimeError as e:
            if '403' in str(e):
                token = login()
                getNewId(str(meta), git, token)
                print(f"   Retried and synced {meta}")
            else:
                print(f"   Failed to sync {meta}: {e}", file=sys.stderr)
                sys.exit(1)

    # commit
    repo.index.commit("chore(sync): upload new models to FDP")
    print(" Committed updates")

    # push
    git.push("-u", "origin", branch_name)
    print(f"  Pushed branch {branch_name}")

    # merge back to master
    git.checkout("master")
    git.merge(branch_name, strategy_option="theirs")
    git.push("origin", "master")
    print(" Merged into master and pushed")

    # delete feature branch
    repo.delete_head(branch_name, force=False)
    print(f"  Deleted branch {branch_name}")

if __name__ == "__main__":
    main()
