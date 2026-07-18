#!/usr/bin/env python3
"""Generates multi-format vocabulary files and developer portal for Croissant.

Reads source Turtle files from docs/, produces serialized vocabulary in
JSON-LD, Turtle, RDF/XML, N-Triples, N-Quads, and CSV formats.
Generates Schema.org-style HTML pages for types, properties, and downloads.

Namespaces (from mlcroissant constants.py / rdf.py):
  cr:     http://mlcommons.org/croissant/       (always http)
  geocr:  http://mlcommons.org/croissant/geo/   (always http)
  rai:    http://mlcommons.org/croissant/RAI/    (always http)
  schema: https://schema.org/ or http://schema.org/ (http/https flavors)
  dct:    http://purl.org/dc/terms/

The http/https distinction applies ONLY to schema.org URIs.
"""

import csv
import os
import rdflib
from rdflib import RDF, RDFS, URIRef, Namespace

# Namespaces (mlcroissant/_src/core/constants.py) 
CR = "http://mlcommons.org/croissant/"
GEOCR = "http://mlcommons.org/croissant/geo/"
RAI = "http://mlcommons.org/croissant/RAI/"
SCHEMA_HTTPS = "https://schema.org/"
SCHEMA_HTTP = "http://schema.org/"
DCT = "http://purl.org/dc/terms/"

# Source TTL configuration (resolved relative to this script's directory)
DIR = os.path.dirname(os.path.abspath(__file__))
SOURCES = {
    "croissant-current": os.path.join(DIR, "docs/croissant.ttl"),
    "croissant-geo": os.path.join(DIR, "docs/croissant_geo.ttl"),
    "croissant-rai": os.path.join(DIR, "docs/croissant_rai.ttl"),
}

# Output directory detection (VDF relative to CWD, otherwise a new build directory)
OUT_DIR = "VDF" if os.path.exists("VDF") and os.path.isdir("VDF") else "build"

def load_graph(path, use_https):
    """Loads a Turtle file, rebinding schema.org to http or https flavor.

    Croissant namespaces (cr, geocr, rai) are always http://.
    Only schema.org varies between http and https.
    """
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # The source TTL uses https://schema.org/. For http flavor, swap it.
    if not use_https:
        content = content.replace(SCHEMA_HTTPS, SCHEMA_HTTP)

    g = rdflib.Graph()
    g.parse(data=content, format="turtle")

    # Bind clean prefixes
    schema_ns = SCHEMA_HTTPS if use_https else SCHEMA_HTTP
    g.bind("cr", Namespace(CR), override=True)
    g.bind("geocr", Namespace(GEOCR), override=True)
    g.bind("rai", Namespace(RAI), override=True)
    g.bind("schema", Namespace(schema_ns), override=True)
    g.bind("dct", Namespace(DCT), override=True)
    return g

def jsonld_context(use_https):
    """Returns a JSON-LD @context dict matching mlcroissant rdf.py make_context()."""
    sc = SCHEMA_HTTPS if use_https else SCHEMA_HTTP
    return {
        "@vocab": sc,
        "cr": CR,
        "geocr": GEOCR,
        "rai": RAI,
        "sc": sc,
        "schema": sc,
        "dct": DCT,
        "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
        "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    }

def serialize_all(g, base, use_https):
    """Serializes graph to all RDF formats."""
    g.serialize(destination=f"{base}.ttl", format="turtle")
    g.serialize(destination=f"{base}.jsonld", format="json-ld", context=jsonld_context(use_https))
    g.serialize(destination=f"{base}.rdf", format="xml")
    g.serialize(destination=f"{base}.nt", format="nt")
    cg = rdflib.ConjunctiveGraph()
    for s, p, o in g:
        cg.add((s, p, o))
    cg.serialize(destination=f"{base}.nq", format="nquads")

def vocab_label(uri):
    """Determines which vocabulary a URI belongs to."""
    s = str(uri)
    if "geo/" in s:
        return "Geo"
    if "RAI/" in s:
        return "RAI"
    return "Core"

def extract_terms(g, use_https):
    """Extracts classes and properties from graph."""
    schema_ns = SCHEMA_HTTPS if use_https else SCHEMA_HTTP
    domain_uri = URIRef(schema_ns + "domainIncludes")
    range_uri = URIRef(schema_ns + "rangeIncludes")

    RDF_CLASS = URIRef("http://www.w3.org/1999/02/22-rdf-syntax-ns#Class")
    RDF_CLASS_LC = URIRef("http://www.w3.org/1999/02/22-rdf-syntax-ns#class")

    types = []
    classes = set(g.subjects(RDF.type, RDFS.Class)) | set(g.subjects(RDF.type, RDF_CLASS)) | set(g.subjects(RDF.type, RDF_CLASS_LC))
    for c in sorted(classes):
        label = g.value(c, RDFS.label) or str(c).rsplit("/", 1)[-1]
        comment = g.value(c, RDFS.comment) or ""
        parents = ", ".join(str(p) for p in g.objects(c, RDFS.subClassOf))
        types.append({"URI": str(c), "Label": str(label), "Comment": str(comment).strip(),
                       "SubClassOf": parents, "Vocabulary": vocab_label(c)})

    props = []
    for p in sorted(set(g.subjects(RDF.type, RDF.Property))):
        label = g.value(p, RDFS.label) or str(p).rsplit("/", 1)[-1]
        comment = g.value(p, RDFS.comment) or ""
        domains = sorted(set(str(d) for d in g.objects(p, domain_uri)) |
                         set(str(d) for d in g.objects(p, RDFS.domain)))
        ranges = sorted(set(str(r) for r in g.objects(p, range_uri)) |
                        set(str(r) for r in g.objects(p, RDFS.range)))
        props.append({"URI": str(p), "Label": str(label), "Comment": str(comment).strip(),
                       "Domain": ", ".join(domains), "Range": ", ".join(ranges),
                       "Vocabulary": vocab_label(p)})
    return types, props

def write_csvs(base, types, props):
    """Writes types and properties CSV files."""
    with open(f"{base}-types.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["URI", "Label", "Comment", "SubClassOf", "Vocabulary"])
        w.writeheader()
        w.writerows(types)
    with open(f"{base}-properties.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["URI", "Label", "Comment", "Domain", "Range", "Vocabulary"])
        w.writeheader()
        w.writerows(props)


# HTML generation 
STYLE = """body{font-family:Arial,sans-serif;margin:0;padding:0}
#hdr{border-top:5px solid #990000;padding:10px 40px;display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #ddd}
#hdr a{color:#990000;text-decoration:none;font-weight:bold}
#logo{font-size:1.5em}
#nav a{margin-left:20px;font-size:.95em}
#nav a:hover{text-decoration:underline}
#main{padding:40px;max-width:1000px;margin:0 auto}
h1{font-weight:normal}
h2{font-weight:normal;border-bottom:1px solid #ccc;padding-bottom:5px}
a{color:#990000;text-decoration:none}
a:hover{text-decoration:underline}
table{width:100%;border-collapse:collapse;margin-top:20px;text-align:left}
th{background:#f2f2f2;padding:10px;border-bottom:2px solid #ccc}
td{padding:8px;border-bottom:1px solid #ddd}
.mono{font-family:monospace}
.search{padding:6px;width:300px;font-size:.95em;margin-bottom:15px}
.box{background:#fcfcfc;border:1px solid #e0e0e0;padding:20px;margin:20px 0}
.fg{display:inline-block;margin-right:20px}
label{font-weight:bold;margin-right:10px}
select{padding:4px;font-size:.95em}
#url{color:#990000;font-family:monospace;font-size:1.05em;margin:15px 0;word-break:break-all}
button{padding:4px 12px;font-size:.95em;cursor:pointer}
#ft{border-top:1px solid #ccc;margin-top:50px;padding:15px 0;text-align:center;font-size:.85em;color:#666}"""

HEADER = """<div id="hdr"><div id="logo"><a href="developers.html">Croissant</a></div>
<div id="nav"><a href="developers.html">Docs</a><a href="types.html">Classes (Types)</a><a href="properties.html">Properties</a></div></div>"""

FILTER_JS = """<script>function filterTable(){var f=document.getElementById("search").value.toLowerCase();
var rows=document.getElementById("tb").getElementsByTagName("tr");
for(var i=0;i<rows.length;i++){var found=false;var cells=rows[i].getElementsByTagName("td");
for(var j=0;j<cells.length;j++){if(cells[j].innerText.toLowerCase().indexOf(f)>-1){found=true;break;}}
rows[i].style.display=found?"":"none";}}</script>"""

def generate_types_html(types):
    rows = "\n".join(
        f'<tr><td class="mono"><a href="{t["URI"]}">{t["URI"]}</a></td>'
        f'<td><b>{t["Label"]}</b></td><td>{t["Comment"]}</td>'
        f'<td>{t["SubClassOf"]}</td><td>{t["Vocabulary"]}</td></tr>'
        for t in types
    )
    html = f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<title>Croissant Classes (Types)</title><style>{STYLE}</style>{FILTER_JS}</head>
<body>{HEADER}<div id="main"><h1>Croissant Vocabulary Classes (Types)</h1>
<input type="text" id="search" class="search" placeholder="Search classes..." oninput="filterTable()">
<table><thead><tr><th>URI</th><th>Label</th><th>Comment</th><th>Subclass Of</th><th>Vocabulary</th></tr></thead>
<tbody id="tb">{rows}</tbody></table></div></body></html>"""
    with open(os.path.join(OUT_DIR, "types.html"), "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Generated {os.path.join(OUT_DIR, 'types.html')}")


def generate_props_html(props):
    rows = "\n".join(
        f'<tr><td class="mono"><a href="{p["URI"]}">{p["URI"]}</a></td>'
        f'<td><b>{p["Label"]}</b></td><td>{p["Comment"]}</td>'
        f'<td>{p["Domain"]}</td><td>{p["Range"]}</td><td>{p["Vocabulary"]}</td></tr>'
        for p in props
    )
    html = f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<title>Croissant Properties</title><style>{STYLE}</style>{FILTER_JS}</head>
<body>{HEADER}<div id="main"><h1>Croissant Vocabulary Properties</h1>
<input type="text" id="search" class="search" placeholder="Search properties..." oninput="filterTable()">
<table><thead><tr><th>URI</th><th>Label</th><th>Comment</th><th>Domain Includes</th><th>Range Includes</th><th>Vocabulary</th></tr></thead>
<tbody id="tb">{rows}</tbody></table></div></body></html>"""
    with open(os.path.join(OUT_DIR, "properties.html"), "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Generated {os.path.join(OUT_DIR, 'properties.html')}")


def generate_developers_html():
    # Build option tags for the file selector
    files = ["croissant-all-http", "croissant-all-https",
             "croissant-current-http", "croissant-current-https",
             "croissant-geo-http", "croissant-geo-https",
             "croissant-rai-http", "croissant-rai-https"]
    opts = "".join(f'<option value="{f}">{f}</option>' for f in files)

    html = f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<title>Croissant for Developers</title><style>{STYLE}</style></head>
<body>{HEADER}<div id="main">
<h1>Croissant for Developers</h1>
<p>This page provides developer-oriented information about Croissant and access to machine-readable representations of the vocabulary.</p>

<h2>Machine Readable Term Definitions</h2>
<ul>
<li>Source files are maintained in Turtle format in our <a href="https://github.com/mlcommons/croissant">Github repository</a>.</li>
<li>Croissant builds on <a href="https://schema.org/">schema.org</a> and its Dataset vocabulary.</li>
<li>Schema.org URIs are available in both <b>http</b> and <b>https</b> flavors. Croissant namespace URIs (<code>cr:</code>, <code>geocr:</code>, <code>rai:</code>) always use <code>http://</code>.</li>
<li>The canonical JSON-LD Context files are available at <a href="context-http.json">context-http.json</a> and <a href="context-https.json">context-https.json</a>.</li>
<li>View all terms on the <a href="types.html">Classes (Types)</a> and <a href="properties.html">Properties</a> pages.</li>
</ul>

<h2>Vocabulary Definition Files</h2>
<p>Select a file and format, then click Download.</p>
<div class="box">
<div class="fg"><label for="fs">File:</label><select id="fs" onchange="upd()">{opts}</select></div>
<div class="fg"><label for="ff">Format:</label><select id="ff" onchange="upd()">
<option value=".jsonld">JSON-LD</option><option value=".ttl">Turtle</option>
<option value=".nt">N-Triples</option><option value=".nq">N-Quads</option>
<option value=".rdf">RDF/XML</option><option value="-types.csv">CSV (Types)</option>
<option value="-properties.csv">CSV (Properties)</option></select></div>
<div id="url"></div>
<button onclick="dl()">Download</button>
</div>
<div id="ft">Croissant Vocabulary Definitions</div>
</div>
function upd(){{var f=document.getElementById("fs").value+document.getElementById("ff").value;
var b=window.location.href.substring(0,window.location.href.lastIndexOf("/")+1);
document.getElementById("url").innerText=b+f;}}
function dl(){{var f=document.getElementById("fs").value+document.getElementById("ff").value;
var a=document.createElement("a");a.href=f;a.download=f;document.body.appendChild(a);a.click();a.removeChild(a);}}
upd();
</script></body></html>"""
    with open(os.path.join(OUT_DIR, "developers.html"), "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Generated {os.path.join(OUT_DIR, 'developers.html')}")

def generate_context_files():
    """Generates the canonical JSON-LD context files for Croissant."""
    import json
    for use_https in (True, False):
        sc = SCHEMA_HTTPS if use_https else SCHEMA_HTTP
        ctx = {
            "@context": {
                "@language": "en",
                "@vocab": sc,
                "citeAs": "cr:citeAs",
                "column": "cr:column",
                "conformsTo": "dct:conformsTo",
                "cr": CR,
                "rai": RAI,
                "geocr": GEOCR,
                "data": {
                    "@id": "cr:data",
                    "@type": "@json"
                },
                "dataType": {
                    "@id": "cr:dataType",
                    "@type": "@vocab"
                },
                "dct": DCT,
                "equivalentProperty": "cr:equivalentProperty",
                "examples": {
                    "@id": "cr:examples",
                    "@type": "@json"
                },
                "extract": "cr:extract",
                "field": "cr:field",
                "fileProperty": "cr:fileProperty",
                "fileObject": "cr:fileObject",
                "fileSet": "cr:fileSet",
                "format": "cr:format",
                "includes": "cr:includes",
                "isLiveDataset": "cr:isLiveDataset",
                "jsonPath": "cr:jsonPath",
                "key": "cr:key",
                "md5": "cr:md5",
                "parentField": "cr:parentField",
                "path": "cr:path",
                "recordSet": "cr:recordSet",
                "references": "cr:references",
                "regex": "cr:regex",
                "repeated": "cr:repeated",
                "replace": "cr:replace",
                "samplingRate": "cr:samplingRate",
                "sc": sc,
                "separator": "cr:separator",
                "source": "cr:source",
                "subField": "cr:subField",
                "transform": "cr:transform",
                "arrayShape": "cr:arrayShape",
                "containedIn": "cr:containedIn",
                "isArray": "cr:isArray",
                "name": {"@container": "@language"},
                "description": {"@container": "@language"}
            }
        }
        suffix = "https" if use_https else "http"
        with open(os.path.join(OUT_DIR, f"context-{suffix}.json"), "w", encoding="utf-8") as f:
            json.dump(ctx, f, indent=2)
    print("Generated canonical JSON-LD context files")

def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    # Load individual graphs in both schema.org flavors
    graphs = {}
    for name, path in SOURCES.items():
        for use_https in (True, False):
            flavor = "https" if use_https else "http"
            graphs[(name, flavor)] = load_graph(path, use_https)

    # Build combined "all" graphs
    for use_https in (True, False):
        flavor = "https" if use_https else "http"
        all_g = rdflib.Graph()
        schema_ns = SCHEMA_HTTPS if use_https else SCHEMA_HTTP
        all_g.bind("cr", Namespace(CR), override=True)
        all_g.bind("geocr", Namespace(GEOCR), override=True)
        all_g.bind("rai", Namespace(RAI), override=True)
        all_g.bind("schema", Namespace(schema_ns), override=True)
        for name in SOURCES:
            all_g += graphs[(name, flavor)]
        graphs[("croissant-all", flavor)] = all_g

    # Generate all assets
    for (name, flavor), g in graphs.items():
        base = os.path.join(OUT_DIR, f"{name}-{flavor}")
        use_https = flavor == "https"
        serialize_all(g, base, use_https)
        types, props = extract_terms(g, use_https)
        write_csvs(base, types, props)
        print(f"Generated assets for {name}-{flavor}")

    # Generate HTML pages from the combined http graph (canonical)
    all_types, all_props = extract_terms(graphs[("croissant-all", "http")], use_https=False)
    generate_types_html(all_types)
    generate_props_html(all_props)
    generate_context_files()
    generate_developers_html()

if __name__ == "__main__":
    main()
