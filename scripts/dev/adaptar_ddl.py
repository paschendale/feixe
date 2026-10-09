"""Adapta a DDL dos dumps do IBGE para o ambiente de dev: remove referências a schemas não exportados
(dominios, bc100grj_hist, ccar), ajusta sintaxe para PostgreSQL 9.6 e tira diretivas de psql 17."""

import re
import sys

MISSING = ("dominios.", "bc100grj_hist.", "ccar.")
src, dst = sys.argv[1], sys.argv[2]
with open(src, encoding="utf-8") as f:
    text = f.read()
text = re.sub(r"^\\(un)?restrict .*\n", "", text, flags=re.M)
text = re.sub(r"^SET transaction_timeout = 0;\n", "", text, flags=re.M)
text = text.replace("EXECUTE FUNCTION", "EXECUTE PROCEDURE")


def identity(m):
    tbl, col, seq = m.group(1), m.group(2), m.group(3)
    return (
        f"CREATE SEQUENCE {seq};\nALTER TABLE {tbl} ALTER COLUMN {col} SET DEFAULT nextval('{seq}'::regclass);\n"
        f"ALTER SEQUENCE {seq} OWNED BY {tbl}.{col};\n"
    )


text = re.sub(
    r"ALTER TABLE (\S+) ALTER COLUMN (\S+) ADD GENERATED (?:ALWAYS|BY DEFAULT) AS IDENTITY "
    r"\(\s*SEQUENCE NAME (\S+)[^;]*?\);\n",
    identity,
    text,
    flags=re.S,
)
text = re.sub(r"^SET default_table_access_method = heap;\n", "", text, flags=re.M)
text = re.sub(r"^SET default_tablespace = .*\n", "", text, flags=re.M)
if len(sys.argv) > 3:  # schemas a criar no inicio (pg_restore -n nao emite CREATE SCHEMA)
    text = "".join(f"CREATE SCHEMA {s};\n" for s in sys.argv[3].split(",")) + text
# blocos: cada objeto do pg_dump começa com "--\n-- Name:"; preserva o preâmbulo
parts = re.split(r"(?=^--\n-- Name: )", text, flags=re.M)
out, dropped = [], {"blocos": 0, "linhas": 0}
for blk in parts:
    m = re.match(r"--\n-- Name: (.*?); Type: (\w+(?: \w+)*);", blk)
    typ = m.group(2) if m else ""
    refs = any(s in blk for s in MISSING)
    if refs and typ not in ("TABLE", "FUNCTION", "VIEW"):
        dropped["blocos"] += 1
        continue
    if refs and typ == "TABLE":
        lines = blk.split("\n")
        keep = []
        for ln in lines:
            if any(s in ln for s in MISSING):
                dropped["linhas"] += 1
                continue
            keep.append(ln)
        # conserta vírgula pendente antes de ");"
        for i in range(1, len(keep)):
            if keep[i].strip() == ");" and keep[i - 1].rstrip().endswith(","):
                keep[i - 1] = keep[i - 1].rstrip()[:-1]
        blk = "\n".join(keep)
    out.append(blk)
with open(dst, "w", encoding="utf-8") as f:
    f.write("".join(out))
print(f"{src} -> {dst}: blocos removidos {dropped['blocos']}, linhas removidas {dropped['linhas']}")
