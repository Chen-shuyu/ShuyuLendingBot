import sys, json
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from sim3 import *
import prices as PR
clean = load_all("clean")
t = PR.table(30, 48, "prod", 8.0)
a, b = ms(2026,10,14), ms(2026,10,24)
out, w, tr = simulate(evidence(clean, 30), t, [50.48, 2.0, 50.0], a, b, [(a, b)], shift=0)
print("窗 C 用實際持有序列（50.48h）：", {k: round(v, 2) for k, v in out[0].items()}, "實際 1.95%／21.0%／10.95%")
print("成交：", [(fmt(x[0]), round(x[1]*36500, 3), x[2]) for x in tr])
