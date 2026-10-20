"""Check company matching and peers on your exchange list.   python scripts/check_intake.py "Company Name" """
import sys
sys.path.insert(0, ".")
from rescope.api import Member1API
from rescope.intake.listings import load_universe

uni = load_universe("data/equity_list.csv")
print(len(uni), "companies loaded")
p = Member1API(universe=uni).resolve(sys.argv[1])
print("matched:", p.name, "|", p.nse_symbol, "|", p.industry)
print("archetype:", p.archetype, p.archetype_confidence)
print("peers:", [x.name for x in p.peers])
print("warnings:", p.warnings)
