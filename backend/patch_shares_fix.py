import pathlib
p = pathlib.Path("d:/7th sem/Project/code/GraphMind/backend/services/export/extractor.py")
t = p.read_text(encoding="utf-8")
old = '    shares_pat = re.compile(r"(\\d[\\d,]*(?:\\.\\d+)?)\\s*(?:shares?|stocks?|units?)", re.IGNORECASE)'
assert old in t, "shares_pat line not found"
new = '''    name_re = re.escape(name)
    shares_pats = [
        re.compile(r"(\\d[\\d,]*(?:\\.\\d+)?)\\s+" + name_re + r"\\s+shares?", re.IGNORECASE),
        re.compile(r"(\\d[\\d,]*(?:\\.\\d+)?)\\s+shares?\\s+of\\s+" + name_re, re.IGNORECASE),
        re.compile(name_re + r"[^\\d]{0,40}?(\\d[\\d,]*(?:\\.\\d+)?)\\s+shares?", re.IGNORECASE),
        re.compile(r"(\\d[\\d,]*(?:\\.\\d+)?)\\s*(?:shares?|stocks?|units?)", re.IGNORECASE),
    ]'''
t = t.replace(old, new)
old2 = """        if not row.get("shares"):
            match = shares_pat.search(fact_text)
            if match:
                row["shares"] = _coerce_number(match.group(1))"""
assert old2 in t, "shares search block not found"
new2 = """        if not row.get("shares"):
            for shares_pat in shares_pats:
                match = shares_pat.search(fact_text)
                if match:
                    # name-anchored patterns capture the qty in group 1
                    # except the "Apple: 10 shares" pattern (group 1 is still qty
                    # because name_re has no groups — re.escape never adds any).
                    row["shares"] = _coerce_number(match.group(1))
                    break"""
t = t.replace(old2, new2)
p.write_text(t, encoding="utf-8")
print("patched extractor")
