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
    g.serialize(destination=f"{base}.nt", format="nt", encoding="utf-8")
    cg = rdflib.Dataset()
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
    vocab_order = {"Core": 0, "Geo": 1, "RAI": 2}
    types.sort(key=lambda x: (vocab_order.get(x["Vocabulary"], 3), x["Label"]))
    props.sort(key=lambda x: (vocab_order.get(x["Vocabulary"], 3), x["Label"]))
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
def format_vocab_badge(vocab):
    """Formats vocabulary name into a colored HTML badge."""
    cls = "badge-core"
    if vocab == "Geo":
        cls = "badge-geo"
    elif vocab == "RAI":
        cls = "badge-rai"
    return f'<span class="badge {cls}">{vocab}</span>'

def format_links(uri_list_str):
    """Converts a comma-separated list of URIs into HTML link tags."""
    if not uri_list_str or not uri_list_str.strip():
        return ""
    uris = [u.strip() for u in uri_list_str.split(",")]
    links = []
    for u in uris:
        if u.startswith("http://") or u.startswith("https://"):
            label = u.split("/")[-1].split("#")[-1]
            links.append(f'<a href="{u}">{label}</a>')
        else:
            links.append(u)
    return ", ".join(links)

STYLE = """
:root {
  --primary: #9c1a1c;
  --primary-hover: #b31b1b;
  --text-main: #1f2937;
  --text-muted: #4b5563;
  --bg-main: #ffffff;
  --bg-alt: #f9fafb;
  --border: #e5e7eb;
  --shadow: 0 1px 3px 0 rgba(0, 0, 0, 0.1), 0 1px 2px 0 rgba(0, 0, 0, 0.06);
  --shadow-lg: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
  --radius: 8px;
  --font-sans: 'Inter', system-ui, -apple-system, sans-serif;
  --font-mono: 'JetBrains Mono', monospace;
}

* {
  box-sizing: border-box;
}

body {
  font-family: var(--font-sans);
  color: var(--text-main);
  background-color: var(--bg-main);
  margin: 0;
  padding: 0;
  line-height: 1.5;
}

#header {
  border-bottom: 3px solid var(--primary);
  background: #ffffff;
  position: sticky;
  top: 0;
  z-index: 50;
  box-shadow: 0 1px 2px 0 rgba(0,0,0,0.05);
}

.header-container {
  max-width: 100%;
  padding: 0.75rem 4rem;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 1.5rem;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 2.5rem;
}

#logo a {
  color: var(--primary);
  text-decoration: none;
  font-size: 1.4rem;
  font-weight: 400;
  letter-spacing: -0.03em;
  transition: opacity 0.2s;
}

#logo a:hover {
  opacity: 0.85;
}

#nav {
  display: flex;
  align-items: center;
  gap: 1.5rem;
}

.nav-link {
  color: var(--text-muted);
  text-decoration: none;
  font-weight: 500;
  font-size: 0.95rem;
  transition: color 0.2s;
  padding: 0.25rem 0;
}

.nav-link:hover {
  color: var(--primary);
  text-decoration: none;
}

.nav-link.active {
  color: var(--primary);
  font-weight: 600;
}

.search-container {
  position: relative;
  width: 280px;
}

.search {
  width: 100%;
  padding: 0.5rem 1rem 0.5rem 2.25rem;
  font-size: 0.9rem;
  font-family: var(--font-sans);
  border: 1px solid var(--border);
  border-radius: 9999px;
  background-color: var(--bg-alt);
  transition: all 0.2s ease;
  outline: none;
}

.search:focus {
  background-color: #ffffff;
}

.search-container::before {
  content: "";
  position: absolute;
  left: 0.85rem;
  top: 50%;
  transform: translateY(-50%);
  width: 1rem;
  height: 1rem;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' fill='none' viewBox='0 0 24 24' stroke='%239ca3af' stroke-width='2'%3E%3Cpath stroke-linecap='round' stroke-linejoin='round' d='M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z' /%3E%3C/svg%3E");
  background-size: contain;
  background-repeat: no-repeat;
  pointer-events: none;
}

#main {
  max-width: 100%;
  padding: 3rem 4rem;
}

h1 {
  font-size: 2.25rem;
  font-weight: 400;
  color: #111827;
  margin-top: 0;
  margin-bottom: 0.75rem;
  letter-spacing: -0.025em;
}

.lead {
  font-size: 1.125rem;
  color: var(--text-muted);
  margin-bottom: 2.5rem;
}

h2 {
  font-size: 1.5rem;
  font-weight: 400;
  color: #111827;
  margin-top: 2.5rem;
  margin-bottom: 1.25rem;
  border-bottom: 1px solid var(--border);
  padding-bottom: 0.5rem;
}

a {
  color: var(--primary);
  text-decoration: none;
  transition: color 0.15s;
}

a:hover {
  text-decoration: underline;
  color: var(--primary-hover);
}

ul {
  padding-left: 1.25rem;
  margin-bottom: 2rem;
}

li {
  margin-bottom: 0.75rem;
}

.download-container {
  margin: 2rem 0;
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.box-row {
  display: flex;
  flex-wrap: wrap;
  gap: 1.5rem;
  align-items: center;
}

.fg {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

label {
  font-weight: 600;
  font-size: 0.95rem;
  color: #374151;
}

select {
  padding: 0.5rem 2rem 0.5rem 0.75rem;
  font-size: 0.95rem;
  font-family: var(--font-sans);
  border: 1px solid var(--border);
  border-radius: 6px;
  background-color: #ffffff;
  cursor: pointer;
  outline: none;
  transition: border-color 0.15s;
  appearance: none;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' fill='none' viewBox='0 0 24 24' stroke='%234b5563' stroke-width='2'%3E%3Cpath stroke-linecap='round' stroke-linejoin='round' d='M19 9l-7 7-7-7' /%3E%3C/svg%3E");
  background-position: right 0.75rem center;
  background-repeat: no-repeat;
  background-size: 1rem;
}


#url {
  font-family: var(--font-mono);
  font-size: 0.95rem;
  color: var(--primary);
  word-break: break-all;
  margin: 0.25rem 0;
}

button {
  background-color: var(--primary);
  color: #ffffff;
  border: none;
  border-radius: 6px;
  padding: 0.625rem 1.5rem;
  font-size: 0.95rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
  align-self: flex-start;
}

button:hover {
  background-color: var(--primary-hover);
}

button:active {
}

.table-container {
  overflow-x: auto;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  margin-top: 1.5rem;
  box-shadow: var(--shadow);
}

table {
  width: 100%;
  border-collapse: collapse;
  text-align: left;
  font-size: 0.925rem;
}

th:nth-child(1), td:nth-child(1) {
  width: 25%;
  min-width: 280px;
}

th:nth-child(2), td:nth-child(2) {
  width: 15%;
  min-width: 180px;
}

th:nth-child(3), td:nth-child(3) {
  width: 35%;
}

th {
  background: var(--bg-alt);
  color: #374151;
  font-weight: 600;
  padding: 0.85rem 1rem;
  border-bottom: 2px solid var(--border);
}

td {
  padding: 1rem;
  border-bottom: 1px solid var(--border);
  vertical-align: top;
  word-break: break-word;
}

tr:last-child td {
  border-bottom: none;
}

tr:hover td {
  background-color: rgba(249, 250, 251, 0.7);
}

.mono {
  font-family: var(--font-mono);
  font-size: 0.85rem;
  word-break: break-all;
}

.badge {
  display: inline-block;
  padding: 0.125rem 0.5rem;
  font-size: 0.75rem;
  font-weight: 600;
  border-radius: 9999px;
  text-transform: uppercase;
}

.badge-core {
  background-color: #eff6ff;
  color: #1e40af;
  border: 1px solid #bfdbfe;
}

.badge-geo {
  background-color: #f0fdf4;
  color: #166534;
  border: 1px solid #bbf7d0;
}

.badge-rai {
  background-color: #faf5ff;
  color: #6b21a8;
  border: 1px solid #e9d5ff;
}

#ft {
  border-top: 1px solid var(--border);
  margin-top: 5rem;
  padding: 2rem 0;
  text-align: center;
  font-size: 0.875rem;
  color: var(--text-muted);
}
"""

def make_header(active_docs="", active_types="", active_props="", search_box="", relative_prefix=""):
    logo_link = relative_prefix or "./"
    docs_link = relative_prefix or "./"
    types_link = f"{relative_prefix}types/"
    props_link = f"{relative_prefix}properties/"
    
    return f"""<header id="header">
  <div class="header-container">
    <div class="header-left">
      <div id="logo"><a href="{logo_link}">Croissant</a></div>
      <nav id="nav">
        <a href="{docs_link}" class="nav-link {active_docs}">Docs</a>
        <a href="{types_link}" class="nav-link {active_types}">Classes (Types)</a>
        <a href="{props_link}" class="nav-link {active_props}">Properties</a>
      </nav>
    </div>
    <div class="header-right">{search_box}</div>
  </div>
</header>"""

FILTER_JS = """<script>
function filterTable(){
  var f=document.getElementById("search").value.toLowerCase();
  var rows=document.getElementById("tb").getElementsByTagName("tr");
  for(var i=0;i<rows.length;i++){
    var found=false;
    var cells=rows[i].getElementsByTagName("td");
    for(var j=0;j<cells.length;j++){
      if(cells[j].innerText.toLowerCase().indexOf(f)>-1){
        found=true;
        break;
      }
    }
    rows[i].style.display=found?"":"none";
  }
}
</script>"""

def generate_types_html(types):
    rows = "\n".join(
        f'<tr><td class="mono"><a href="{t["URI"]}">{t["URI"]}</a></td>'
        f'<td>{t["Label"]}</td><td>{t["Comment"]}</td>'
        f'<td>{format_links(t["SubClassOf"])}</td>'
        f'<td>{format_vocab_badge(t["Vocabulary"])}</td></tr>'
        for t in types
    )
    header_html = make_header(
        active_docs="",
        active_types="active",
        active_props="",
        search_box='<div class="search-container"><input type="text" id="search" class="search" placeholder="Search classes..." oninput="filterTable()"></div>',
        relative_prefix="../"
    )
    html = f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<title>Croissant Classes (Types)</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>{STYLE}</style>{FILTER_JS}</head>
<body>{header_html}<div id="main"><h1>Croissant Vocabulary Classes (Types)</h1>
<div class="table-container">
<table><thead><tr><th>URI</th><th>Label</th><th>Comment</th><th>Subclass Of</th><th>Vocabulary</th></tr></thead>
<tbody id="tb">{rows}</tbody></table>
</div>
</div></body></html>"""
    with open(os.path.join(OUT_DIR, "types/index.html"), "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Generated {os.path.join(OUT_DIR, 'types/index.html')}")


def generate_props_html(props):
    rows = "\n".join(
        f'<tr><td class="mono"><a href="{p["URI"]}">{p["URI"]}</a></td>'
        f'<td>{p["Label"]}</td><td>{p["Comment"]}</td>'
        f'<td>{format_links(p["Domain"])}</td><td>{format_links(p["Range"])}</td>'
        f'<td>{format_vocab_badge(p["Vocabulary"])}</td></tr>'
        for p in props
    )
    header_html = make_header(
        active_docs="",
        active_types="",
        active_props="active",
        search_box='<div class="search-container"><input type="text" id="search" class="search" placeholder="Search properties..." oninput="filterTable()"></div>',
        relative_prefix="../"
    )
    html = f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<title>Croissant Properties</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>{STYLE}</style>{FILTER_JS}</head>
<body>{header_html}<div id="main"><h1>Croissant Vocabulary Properties</h1>
<div class="table-container">
<table><thead><tr><th>URI</th><th>Label</th><th>Comment</th><th>Domain Includes</th><th>Range Includes</th><th>Vocabulary</th></tr></thead>
<tbody id="tb">{rows}</tbody></table>
</div>
</div></body></html>"""
    with open(os.path.join(OUT_DIR, "properties/index.html"), "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Generated {os.path.join(OUT_DIR, 'properties/index.html')}")


def generate_index_html():
    # Build option tags for the file selector
    files = ["croissant-all-http", "croissant-all-https",
             "croissant-current-http", "croissant-current-https",
             "croissant-geo-http", "croissant-geo-https",
             "croissant-rai-http", "croissant-rai-https"]
    opts = "".join(f'<option value="{f}">{f}</option>' for f in files)

    header_html = make_header(
        active_docs="active",
        active_types="",
        active_props="",
        search_box="",
        relative_prefix=""
    )
    html = f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<title>Croissant for Developers</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>{STYLE}</style></head>
<body>{header_html}<div id="main">
<h1>Croissant for Developers</h1>
<p class="lead">This page provides developer-oriented information about Croissant and access to machine-readable representations of the vocabulary.</p>

<h2>Machine Readable Term Definitions</h2>
<ul>
<li>Source files are maintained in Turtle format in our <a href="https://github.com/mlcommons/croissant">Github repository</a>.</li>
<li>Croissant builds on <a href="https://schema.org/">schema.org</a> and its Dataset vocabulary.</li>
<li>Schema.org URIs are available in both <b>http</b> and <b>https</b>. Croissant namespace URIs (<a href="http://mlcommons.org/croissant/1.0"><code>cr:</code></a>, <a href="http://mlcommons.org/croissant/geo/1.0"><code>geo:</code></a>, <a href="https://mlcommons.org/croissant/RAI/1.0"><code>rai:</code></a>) always use <code>http://</code>.</li>
<li>The canonical JSON-LD Context files are available at <a href="context-http.json">context-http.json</a> and <a href="context-https.json">context-https.json</a>.</li>
<li>View all terms on the <a href="types/">Classes (Types)</a> and <a href="properties/">Properties</a> pages.</li>
</ul>

<h2>Vocabulary Definition Files</h2>
<p>Select a file and format, then click Download.</p>
<div class="download-container">
<div class="box-row">
<div class="fg"><label for="fs">File:</label><select id="fs" onchange="upd()">{opts}</select></div>
<div class="fg"><label for="ff">Format:</label><select id="ff" onchange="upd()">
<option value=".jsonld">JSON-LD</option><option value=".ttl">Turtle</option>
<option value=".nt">N-Triples</option><option value=".nq">N-Quads</option>
<option value=".rdf">RDF/XML</option><option value="-types.csv">CSV (Types)</option>
<option value="-properties.csv">CSV (Properties)</option></select></div>
</div>
<div id="url"></div>
<button onclick="dl()">Download</button>
</div>
<div id="ft">Croissant Vocabulary Definitions</div>
</div>
<script>
function upd() {{
  var f=document.getElementById("fs").value+document.getElementById("ff").value;
  var b=window.location.href.substring(0,window.location.href.lastIndexOf("/")+1);
  var url = b+f;
  var container = document.getElementById("url");
  container.textContent = '';
  var a = document.createElement("a");
  a.href = url;
  a.target = "_blank";
  a.textContent = url;
  container.appendChild(a);
}}
function dl() {{
  var f=document.getElementById("fs").value+document.getElementById("ff").value;
  var a=document.createElement("a");
  a.href=f;
  a.download=f;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}}
upd();
</script></body></html>"""
    with open(os.path.join(OUT_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Generated {os.path.join(OUT_DIR, 'index.html')}")

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
    os.makedirs(os.path.join(OUT_DIR, "types"), exist_ok=True)
    os.makedirs(os.path.join(OUT_DIR, "properties"), exist_ok=True)

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
    generate_index_html()

if __name__ == "__main__":
    main()
