import pandapower as pp 
from pandapower import from_excel
net=from_excel(r"C:\Users\anton\Desktop\nando_pp\excels\net_pp.xlsx")
net.ext_grid['s_sc_max_mva'] = 1000
net.ext_grid['rx_max'] = 0.1
pp.runpp_3ph(net)