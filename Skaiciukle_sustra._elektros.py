import streamlit as st
import pandas as pd
import plotly.graph_objects as go

st.set_page_config(page_title="Saulės elektrinės planų skaičiuoklė", layout="wide")

st.title("☀️ Saulės elektrinės mokėjimo planų skaičiuoklė")
st.markdown("### Realūs mėnesiniai duomenys + kaupiklis + EV krovimo namuose / darbe palyginimas")

st.caption(
    "Skaičiavimas remiasi realiais mėnesiniais inverterio / ESO duomenimis. "
    "Kaupiklio efektas ir EV namų krovimo įtaka modeliuojami iš mėnesinių balansų."
)

# ============================================================
# KONSTANTOS
# ============================================================

MONTH_NAMES_LT = {
    1: "Sausis",
    2: "Vasaris",
    3: "Kovas",
    4: "Balandis",
    5: "Gegužė",
    6: "Birželis",
    7: "Liepa",
    8: "Rugpjūtis",
    9: "Rugsėjis",
    10: "Spalis",
    11: "Lapkritis",
    12: "Gruodis",
}

DAYS_IN_MONTH = {
    1: 31, 2: 28, 3: 31, 4: 30,
    5: 31, 6: 30, 7: 31, 8: 31,
    9: 30, 10: 31, 11: 30, 12: 31
}

DEFAULT_MONTHLY_DATA = pd.DataFrame({
    "Mėn_nr": list(range(1, 13)),
    "Mėnuo": [MONTH_NAMES_LT[i] for i in range(1, 13)],
    "Pagamino inverteris": [138, 537, 1159, 1787, 1951, 2300, 1881, 1750, 1157, 697, 225, 100],
    "Atiduota į ESO": [60, 360, 918, 1562, 1656, 1582, 1223, 1089, 752, 217, 14, 10],
    "Gauta iš ESO": [1104, 1216, 605, 264, 314, 304, 90, 84, 50, 425, 908, 950],
})

# ============================================================
# PAGALBINĖS FUNKCIJOS
# ============================================================

def clean_and_validate_input(df_input: pd.DataFrame) -> pd.DataFrame:
    required_cols = ["Mėn_nr", "Mėnuo", "Pagamino inverteris", "Atiduota į ESO", "Gauta iš ESO"]
    missing = [c for c in required_cols if c not in df_input.columns]
    if missing:
        st.error(f"Trūksta stulpelių: {missing}")
        st.stop()

    df = df_input.copy()

    numeric_cols = ["Mėn_nr", "Pagamino inverteris", "Atiduota į ESO", "Gauta iš ESO"]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    if df[numeric_cols].isna().any().any():
        st.error("Yra tuščių arba neskaitinių reikšmių skaitiniuose stulpeliuose.")
        st.stop()

    if (df[numeric_cols] < 0).any().any():
        st.error("Neigiamos reikšmės neleidžiamos.")
        st.stop()

    if len(df) != 12:
        st.error("Lentelėje turi būti tiksliai 12 eilučių – po vieną kiekvienam mėnesiui.")
        st.stop()

    if set(df["Mėn_nr"].astype(int).tolist()) != set(range(1, 13)):
        st.error("Mėn_nr turi būti visi mėnesiai nuo 1 iki 12.")
        st.stop()

    if (df["Atiduota į ESO"] > df["Pagamino inverteris"]).any():
        bad_months = df.loc[df["Atiduota į ESO"] > df["Pagamino inverteris"], "Mėnuo"].tolist()
        st.error(
            f"Šiuose mėnesiuose 'Atiduota į ESO' > 'Pagamino inverteris': {', '.join(bad_months)}. "
            "Pagal šį modelį taip būti neturėtų."
        )
        st.stop()

    df["Mėn_nr"] = df["Mėn_nr"].astype(int)
    return df


def reorder_by_accounting_mode(df: pd.DataFrame, accounting_mode: str) -> pd.DataFrame:
    if accounting_mode == "Balandis–Kovas (ESO kaupimo ciklas)":
        order = [4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2, 3]
    else:
        order = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]

    order_map = {m: i for i, m in enumerate(order)}
    out = df.copy()
    out["sort_order"] = out["Mėn_nr"].map(order_map)
    out = out.sort_values("sort_order").drop(columns=["sort_order"]).reset_index(drop=True)
    return out


def build_baseline_energy_df(df_input: pd.DataFrame) -> pd.DataFrame:
    """
    Bazinis scenarijus pagal realius istorinius duomenis be papildomo EV krovimo namuose.
    """
    df = df_input.copy()
    df["Momentiškai suvartota"] = df["Pagamino inverteris"] - df["Atiduota į ESO"]
    df["Bendras vartojimas"] = df["Momentiškai suvartota"] + df["Gauta iš ESO"]
    df["Mėnesio balansas"] = df["Atiduota į ESO"] - df["Gauta iš ESO"]
    return df


def add_ev_home_load(df_base: pd.DataFrame, ev_home_kwh_annual: float) -> pd.DataFrame:
    """
    Papildomas EV krovimas namuose pridedamas kaip papildomas metinis poreikis.
    Kadangi neturime valandinių duomenų, paskirstome tolygiai per 12 mėn.
    """
    df = df_base.copy()

    ev_home_monthly = ev_home_kwh_annual / 12.0

    df["EV namuose"] = ev_home_monthly
    df["Gauta iš ESO be kaupiklio (su EV)"] = df["Gauta iš ESO"] + ev_home_monthly
    df["Bendras vartojimas su EV"] = df["Bendras vartojimas"] + ev_home_monthly

    # Kad planų skaičiavimas būtų paprastas ir nuoseklus:
    df["Gauta iš ESO scenarijui"] = df["Gauta iš ESO be kaupiklio (su EV)"]
    df["Bendras vartojimas scenarijui"] = df["Bendras vartojimas su EV"]

    return df


def apply_battery_model(
    df_scenario: pd.DataFrame,
    battery_capacity_kwh: float,
    battery_min_soc_pct: float,
    battery_efficiency_pct: float,
    battery_utilization_pct: float
) -> pd.DataFrame:
    """
    Kaupiklio modelis:
    - bazinis eksportas = Atiduota į ESO
    - bazinis importas scenarijui = Gauta iš ESO scenarijui
    - baterija gali dalį eksporto perkelti į vėlesnį vartojimą

    Naudojamas mėnesinis vidutinės dienos modelis.
    """
    df = df_scenario.copy()

    if battery_capacity_kwh <= 0 or battery_efficiency_pct <= 0 or battery_utilization_pct <= 0:
        df["Į bateriją iš PV"] = 0.0
        df["Iš baterijos į namą"] = 0.0
        df["Kaupiklio nuostoliai"] = 0.0
        df["Atiduota į ESO po kaupiklio"] = df["Atiduota į ESO"]
        df["Gauta iš ESO po kaupiklio"] = df["Gauta iš ESO scenarijui"]
        df["Bendra vietoje padengta po kaupiklio"] = df["Momentiškai suvartota"]
        df["Vietoje padengta dalis po kaupiklio %"] = (
            df["Bendra vietoje padengta po kaupiklio"] / df["Bendras vartojimas scenarijui"] * 100
        ).fillna(0)
        return df

    charge_window = battery_capacity_kwh * (1 - battery_min_soc_pct / 100.0)
    roundtrip_eff = battery_efficiency_pct / 100.0
    utilization = battery_utilization_pct / 100.0

    battery_charge_list = []
    battery_discharge_list = []
    battery_loss_list = []
    export_after_list = []
    import_after_list = []
    onsite_after_list = []
    onsite_share_after_list = []

    for _, row in df.iterrows():
        month = int(row["Mėn_nr"])
        days = DAYS_IN_MONTH[month]

        exported = float(row["Atiduota į ESO"])
        imported = float(row["Gauta iš ESO scenarijui"])
        direct_onsite = float(row["Momentiškai suvartota"])
        total_consumption = float(row["Bendras vartojimas scenarijui"])

        daily_export = exported / days
        daily_import = imported / days

        daily_battery_to_home_theoretical = min(
            daily_import,
            daily_export * roundtrip_eff,
            charge_window * roundtrip_eff
        )

        daily_battery_to_home = daily_battery_to_home_theoretical * utilization
        monthly_battery_to_home = daily_battery_to_home * days

        monthly_pv_to_battery = monthly_battery_to_home / roundtrip_eff if roundtrip_eff > 0 else 0.0

        monthly_pv_to_battery = min(monthly_pv_to_battery, exported)
        monthly_battery_to_home = min(monthly_battery_to_home, imported)

        battery_losses = monthly_pv_to_battery - monthly_battery_to_home

        export_after = max(0.0, exported - monthly_pv_to_battery)
        import_after = max(0.0, imported - monthly_battery_to_home)
        onsite_after = direct_onsite + monthly_battery_to_home
        onsite_share_after = (onsite_after / total_consumption * 100) if total_consumption > 0 else 0.0

        battery_charge_list.append(monthly_pv_to_battery)
        battery_discharge_list.append(monthly_battery_to_home)
        battery_loss_list.append(battery_losses)
        export_after_list.append(export_after)
        import_after_list.append(import_after)
        onsite_after_list.append(onsite_after)
        onsite_share_after_list.append(onsite_share_after)

    df["Į bateriją iš PV"] = battery_charge_list
    df["Iš baterijos į namą"] = battery_discharge_list
    df["Kaupiklio nuostoliai"] = battery_loss_list
    df["Atiduota į ESO po kaupiklio"] = export_after_list
    df["Gauta iš ESO po kaupiklio"] = import_after_list
    df["Bendra vietoje padengta po kaupiklio"] = onsite_after_list
    df["Vietoje padengta dalis po kaupiklio %"] = onsite_share_after_list

    return df


def calculate_plan1(df: pd.DataFrame, buy_price: float, return_fee: float, compensation_tariff: float):
    bank = 0.0
    total_before_comp = 0.0
    rows = []

    for _, row in df.iterrows():
        exported = float(row["Atiduota į ESO"])
        imported = float(row["Gauta iš ESO"])

        available_this_month = bank + exported
        retrieved = min(imported, available_this_month)
        bought = imported - retrieved
        bank = available_this_month - retrieved

        retrieval_cost = retrieved * return_fee
        purchase_cost = bought * buy_price
        month_cost = retrieval_cost + purchase_cost
        total_before_comp += month_cost

        rows.append({
            "Mėnuo": row["Mėnuo"],
            "Atiduota į ESO": exported,
            "Gauta iš ESO": imported,
            "Atsiimta iš sukaupto": retrieved,
            "Pirkta iš tiekėjo": bought,
            "Atsiėmimo mokestis": retrieval_cost,
            "Pirkimo kaina": purchase_cost,
            "Mėn. kaina": month_cost,
            "Likutis tinkle mėn. gale": bank,
        })

    compensation = bank * compensation_tariff
    total_after_comp = total_before_comp - compensation
    return total_after_comp, pd.DataFrame(rows), bank, compensation


def calculate_plan2(df: pd.DataFrame, buy_price: float, monthly_fee_per_kw: float, compensation_tariff: float, pv_allowed: float):
    bank = 0.0
    total_before_comp = 0.0
    fixed_monthly_fee = monthly_fee_per_kw * pv_allowed
    rows = []

    for _, row in df.iterrows():
        exported = float(row["Atiduota į ESO"])
        imported = float(row["Gauta iš ESO"])

        available_this_month = bank + exported
        retrieved = min(imported, available_this_month)
        bought = imported - retrieved
        bank = available_this_month - retrieved

        purchase_cost = bought * buy_price
        month_cost = fixed_monthly_fee + purchase_cost
        total_before_comp += month_cost

        rows.append({
            "Mėnuo": row["Mėnuo"],
            "Atiduota į ESO": exported,
            "Gauta iš ESO": imported,
            "Atsiimta iš sukaupto": retrieved,
            "Pirkta iš tiekėjo": bought,
            "Fiksuotas mokestis": fixed_monthly_fee,
            "Pirkimo kaina": purchase_cost,
            "Mėn. kaina": month_cost,
            "Likutis tinkle mėn. gale": bank,
        })

    compensation = bank * compensation_tariff
    total_after_comp = total_before_comp - compensation
    return total_after_comp, pd.DataFrame(rows), bank, compensation


def calculate_plan3(df: pd.DataFrame, buy_price: float, eso_keeps_pct: float, compensation_tariff: float):
    bank = 0.0
    total_before_comp = 0.0
    eso_return_pct = (100.0 - eso_keeps_pct) / 100.0
    rows = []

    for _, row in df.iterrows():
        exported = float(row["Atiduota į ESO"])
        imported = float(row["Gauta iš ESO"])

        effective_export = exported * eso_return_pct
        eso_kept = exported - effective_export

        available_this_month = bank + effective_export
        retrieved = min(imported, available_this_month)
        bought = imported - retrieved
        bank = available_this_month - retrieved

        purchase_cost = bought * buy_price
        month_cost = purchase_cost
        total_before_comp += month_cost

        rows.append({
            "Mėnuo": row["Mėnuo"],
            "Atiduota į ESO": exported,
            "ESO grąžina į banką": effective_export,
            "ESO pasilieka": eso_kept,
            "Gauta iš ESO": imported,
            "Atsiimta iš sukaupto": retrieved,
            "Pirkta iš tiekėjo": bought,
            "Pirkimo kaina": purchase_cost,
            "Mėn. kaina": month_cost,
            "Likutis tinkle mėn. gale": bank,
        })

    compensation = bank * compensation_tariff
    total_after_comp = total_before_comp - compensation
    return total_after_comp, pd.DataFrame(rows), bank, compensation


def round_display_df(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in out.columns:
        if pd.api.types.is_numeric_dtype(out[col]):
            if "kaina" in col.lower() or "mokestis" in col.lower():
                out[col] = out[col].round(2)
            else:
                out[col] = out[col].round(1)
    return out


def cumulative_cost_series(plan_df: pd.DataFrame, final_total_cost: float):
    months = plan_df["Mėnuo"].tolist()
    cum = plan_df["Mėn. kaina"].cumsum().tolist()
    months_plus = months + ["Metų pabaiga"]
    cum_plus = cum + [final_total_cost]
    return months_plus, cum_plus


def evaluate_plans(plan_df: pd.DataFrame, buy_price: float, plan1_return_fee: float, plan2_monthly_fee: float,
                   plan3_eso_keeps_pct: float, compensation_tariff: float, pv_allowed: float):
    p1_cost, p1_monthly, p1_left, p1_comp = calculate_plan1(
        plan_df, buy_price, plan1_return_fee, compensation_tariff
    )
    p2_cost, p2_monthly, p2_left, p2_comp = calculate_plan2(
        plan_df, buy_price, plan2_monthly_fee, compensation_tariff, pv_allowed
    )
    p3_cost, p3_monthly, p3_left, p3_comp = calculate_plan3(
        plan_df, buy_price, plan3_eso_keeps_pct, compensation_tariff
    )

    return {
        "plan1_cost": p1_cost,
        "plan2_cost": p2_cost,
        "plan3_cost": p3_cost,
        "plan1_monthly": p1_monthly,
        "plan2_monthly": p2_monthly,
        "plan3_monthly": p3_monthly,
        "plan1_left": p1_left,
        "plan2_left": p2_left,
        "plan3_left": p3_left,
        "plan1_comp": p1_comp,
        "plan2_comp": p2_comp,
        "plan3_comp": p3_comp,
    }


# ============================================================
# SIDEBAR
# ============================================================

st.sidebar.header("⚙️ Nustatymai")

st.sidebar.subheader("Elektrinės duomenys")
pv_power = st.sidebar.number_input(
    "Elektrinės įrengtoji galia (kW)",
    min_value=0.0,
    value=14.0,
    step=0.5
)

pv_allowed = st.sidebar.number_input(
    "Leistina generuoti galia (kW)",
    min_value=0.0,
    value=10.0,
    step=0.5
)

st.sidebar.subheader("Metinių duomenų patikra")
declared_direct = st.sidebar.number_input(
    "Momentinis metinis vartojimas / vietoje suvartota (kWh)",
    min_value=0.0,
    value=4239.0,
    step=1.0
)

declared_total_need = st.sidebar.number_input(
    "Metinis elektros poreikis (kWh)",
    min_value=0.0,
    value=10553.0,
    step=1.0
)

st.sidebar.subheader("🔋 Kaupiklis")
battery_capacity = st.sidebar.number_input(
    "Kaupiklio talpa (kWh)",
    min_value=0.0,
    value=14.4,
    step=0.1
)

battery_min_soc = st.sidebar.number_input(
    "Min. SOC (%)",
    min_value=0.0,
    max_value=100.0,
    value=20.0,
    step=5.0
)

battery_efficiency = st.sidebar.number_input(
    "Kaupiklio efektyvumas (%)",
    min_value=0.0,
    max_value=100.0,
    value=90.0,
    step=1.0
)

battery_utilization = st.sidebar.number_input(
    "Kaupiklio panaudojimo koeficientas (%)",
    min_value=0.0,
    max_value=100.0,
    value=100.0,
    step=5.0,
    help="Naudinga konservatyvesniam vertinimui, nes naudojami mėnesiniai, o ne valandiniai duomenys."
)

st.sidebar.subheader("🚗 EV duomenys")
ev_km_per_year = st.sidebar.number_input(
    "EV km per metus",
    min_value=0.0,
    value=15000.0,
    step=1000.0
)

ev_consumption = st.sidebar.number_input(
    "EV sąnaudos (kWh/100km)",
    min_value=0.0,
    value=19.0,
    step=0.5
)

ev_charge_work_pct = st.sidebar.slider(
    "EV krovimo dalis DARBE (%)",
    min_value=0,
    max_value=100,
    value=100,
    step=5
)

ev_price_work = st.sidebar.number_input(
    "EV kaina darbe (€/kWh)",
    min_value=0.0,
    value=0.13,
    step=0.01,
    format="%.4f"
)

st.sidebar.subheader("Apskaitos tvarka")
accounting_mode = st.sidebar.selectbox(
    "Mėnesių eiliškumas planams",
    [
        "Balandis–Kovas (ESO kaupimo ciklas)",
        "Sausis–Gruodis (kalendoriniai metai)"
    ],
    index=0
)

st.sidebar.subheader("💰 Tarifai")
buy_price = st.sidebar.number_input(
    "Perkamos elektros kaina (€/kWh)",
    min_value=0.0,
    value=0.2347,
    step=0.01,
    format="%.4f"
)

plan1_return_fee = st.sidebar.number_input(
    "Planas 1: kaina už atgautą kWh (€/kWh)",
    min_value=0.0,
    value=0.0726,
    step=0.001,
    format="%.4f"
)

plan2_monthly_fee = st.sidebar.number_input(
    "Planas 2: mokestis už kW per mėn. (€/kW/mėn.)",
    min_value=0.0,
    value=5.0336,
    step=0.1,
    format="%.4f"
)

plan3_eso_keeps_pct = st.sidebar.number_input(
    "Planas 3: ESO pasilieka (%)",
    min_value=0.0,
    max_value=100.0,
    value=37.0,
    step=1.0
)

compensation_tariff = st.sidebar.number_input(
    "Metų pabaigos kompensacijos tarifas (€/kWh)",
    min_value=0.0,
    value=0.01,
    step=0.005,
    format="%.4f"
)

if pv_allowed > pv_power and pv_power > 0:
    st.sidebar.warning("Leistina generuoti galia yra didesnė už įrengtąją galią. Patikrink įvestį.")

# ============================================================
# DUOMENŲ ĮVEDIMAS
# ============================================================

st.markdown("---")
st.header("📥 Realūs mėnesiniai duomenys")

st.markdown(
    "Žemiau įrašyti tavo pateikti realūs duomenys. Jei reikia, gali juos redaguoti."
)

edited_data = st.data_editor(
    DEFAULT_MONTHLY_DATA,
    hide_index=True,
    use_container_width=True,
    num_rows="fixed",
    disabled=["Mėn_nr", "Mėnuo"]
)

raw_df = clean_and_validate_input(edited_data)

# ============================================================
# BAZINIS SCENARIJUS
# ============================================================

baseline_df = build_baseline_energy_df(raw_df)

annual_generated = baseline_df["Pagamino inverteris"].sum()
annual_exported = baseline_df["Atiduota į ESO"].sum()
annual_imported = baseline_df["Gauta iš ESO"].sum()
annual_direct = baseline_df["Momentiškai suvartota"].sum()
annual_total_consumption = baseline_df["Bendras vartojimas"].sum()

direct_diff = annual_direct - declared_direct
need_diff = annual_total_consumption - declared_total_need

# ============================================================
# EV SKAIČIAVIMAS
# ============================================================

ev_annual_kwh = ev_km_per_year * ev_consumption / 100.0
ev_work_share = ev_charge_work_pct / 100.0
ev_home_share = 1.0 - ev_work_share

ev_home_kwh = ev_annual_kwh * ev_home_share
ev_work_kwh = ev_annual_kwh * ev_work_share
ev_work_cost = ev_work_kwh * ev_price_work

# Scenarijus su papildomu EV krovimu namuose
scenario_no_battery_df = add_ev_home_load(baseline_df, ev_home_kwh)
scenario_no_battery_df = reorder_by_accounting_mode(scenario_no_battery_df, accounting_mode)

# Scenarijus su kaupikliu
scenario_with_battery_df = apply_battery_model(
    df_scenario=scenario_no_battery_df,
    battery_capacity_kwh=battery_capacity,
    battery_min_soc_pct=battery_min_soc,
    battery_efficiency_pct=battery_efficiency,
    battery_utilization_pct=battery_utilization
)

# ============================================================
# PLANŲ DUOMENYS
# ============================================================

plan_input_no_battery = scenario_no_battery_df[[
    "Mėn_nr", "Mėnuo", "Atiduota į ESO", "Gauta iš ESO scenarijui"
]].rename(columns={
    "Gauta iš ESO scenarijui": "Gauta iš ESO"
})

plan_input_with_battery = scenario_with_battery_df[[
    "Mėn_nr", "Mėnuo", "Atiduota į ESO po kaupiklio", "Gauta iš ESO po kaupiklio"
]].rename(columns={
    "Atiduota į ESO po kaupiklio": "Atiduota į ESO",
    "Gauta iš ESO po kaupiklio": "Gauta iš ESO"
})

# Be kaupiklio
plans_no_battery = evaluate_plans(
    plan_df=plan_input_no_battery,
    buy_price=buy_price,
    plan1_return_fee=plan1_return_fee,
    plan2_monthly_fee=plan2_monthly_fee,
    plan3_eso_keeps_pct=plan3_eso_keeps_pct,
    compensation_tariff=compensation_tariff,
    pv_allowed=pv_allowed
)

# Su kaupikliu
plans_with_battery = evaluate_plans(
    plan_df=plan_input_with_battery,
    buy_price=buy_price,
    plan1_return_fee=plan1_return_fee,
    plan2_monthly_fee=plan2_monthly_fee,
    plan3_eso_keeps_pct=plan3_eso_keeps_pct,
    compensation_tariff=compensation_tariff,
    pv_allowed=pv_allowed
)

# Galutinės bendros metinės kainos = namų planas + EV krovimas darbe
total_plan1_with_battery = plans_with_battery["plan1_cost"] + ev_work_cost
total_plan2_with_battery = plans_with_battery["plan2_cost"] + ev_work_cost
total_plan3_with_battery = plans_with_battery["plan3_cost"] + ev_work_cost

total_plan1_no_battery = plans_no_battery["plan1_cost"] + ev_work_cost
total_plan2_no_battery = plans_no_battery["plan2_cost"] + ev_work_cost
total_plan3_no_battery = plans_no_battery["plan3_cost"] + ev_work_cost

# ============================================================
# SUVESTINĖS REIKŠMĖS
# ============================================================

annual_ev_home_added = scenario_no_battery_df["EV namuose"].sum()
annual_total_consumption_with_ev = scenario_no_battery_df["Bendras vartojimas scenarijui"].sum()
annual_import_with_ev_no_battery = scenario_no_battery_df["Gauta iš ESO scenarijui"].sum()

annual_battery_charge = scenario_with_battery_df["Į bateriją iš PV"].sum()
annual_battery_discharge = scenario_with_battery_df["Iš baterijos į namą"].sum()
annual_battery_losses = scenario_with_battery_df["Kaupiklio nuostoliai"].sum()
annual_export_after_battery = scenario_with_battery_df["Atiduota į ESO po kaupiklio"].sum()
annual_import_after_battery = scenario_with_battery_df["Gauta iš ESO po kaupiklio"].sum()
annual_onsite_after_battery = scenario_with_battery_df["Bendra vietoje padengta po kaupiklio"].sum()

# ============================================================
# DISPLAY DATAFRAMES
# ============================================================

baseline_disp = round_display_df(reorder_by_accounting_mode(baseline_df, accounting_mode))
scenario_no_battery_disp = round_display_df(scenario_no_battery_df)
scenario_with_battery_disp = round_display_df(scenario_with_battery_df)

plan1_no_battery_disp = round_display_df(plans_no_battery["plan1_monthly"])
plan2_no_battery_disp = round_display_df(plans_no_battery["plan2_monthly"])
plan3_no_battery_disp = round_display_df(plans_no_battery["plan3_monthly"])

plan1_with_battery_disp = round_display_df(plans_with_battery["plan1_monthly"])
plan2_with_battery_disp = round_display_df(plans_with_battery["plan2_monthly"])
plan3_with_battery_disp = round_display_df(plans_with_battery["plan3_monthly"])

# ============================================================
# REZULTATAI
# ============================================================

st.markdown("---")
st.header("📊 Faktinių istorinių duomenų suvestinė")

col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("Pagamino inverteris", f"{annual_generated:.0f} kWh")
with col2:
    st.metric("Atiduota į ESO", f"{annual_exported:.0f} kWh")
with col3:
    st.metric("Gauta iš ESO", f"{annual_imported:.0f} kWh")
with col4:
    st.metric("Momentiškai suvartota vietoje", f"{annual_direct:.0f} kWh")

col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("Bendras vartojimas", f"{annual_total_consumption:.0f} kWh")
with col2:
    specific_yield = annual_generated / pv_power if pv_power > 0 else 0.0
    st.metric("Specifinė generacija", f"{specific_yield:.0f} kWh/kW")
with col3:
    base_self_share = annual_direct / annual_total_consumption * 100 if annual_total_consumption > 0 else 0
    st.metric("Padengta vietoje be kaupiklio", f"{base_self_share:.1f}%")
with col4:
    st.metric("Eksporto-importo balansas", f"{annual_exported - annual_imported:.0f} kWh")

st.markdown("---")
st.subheader("🔎 Metinių skaičių patikra")

col1, col2 = st.columns(2)
with col1:
    st.metric(
        "Deklaruotas momentinis / vietoje suvartotas kiekis",
        f"{declared_direct:.0f} kWh",
        delta=f"{direct_diff:+.0f} kWh"
    )
with col2:
    st.metric(
        "Deklaruotas metinis elektros poreikis",
        f"{declared_total_need:.0f} kWh",
        delta=f"{need_diff:+.0f} kWh"
    )

if abs(direct_diff) < 0.5 and abs(need_diff) < 0.5:
    st.success("Mėnesiniai duomenys tiksliai sutampa su deklaruotais metiniais skaičiais.")
else:
    st.warning("Yra neatitikimas tarp deklaruotų metinių dydžių ir sumos iš mėnesių.")

st.info(
    "Formulės:\n"
    "- Momentiškai suvartota = Pagamino inverteris - Atiduota į ESO\n"
    "- Bendras vartojimas = Momentiškai suvartota + Gauta iš ESO"
)

# ============================================================
# EV SUVESTINĖ
# ============================================================

st.markdown("---")
st.header("🚗 EV scenarijus")

col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("EV metinis poreikis", f"{ev_annual_kwh:.0f} kWh")
with col2:
    st.metric("EV kraunama namuose", f"{ev_home_kwh:.0f} kWh ({ev_home_share*100:.0f}%)")
with col3:
    st.metric("EV kraunama darbe", f"{ev_work_kwh:.0f} kWh ({ev_work_share*100:.0f}%)")
with col4:
    st.metric("EV krovimo darbe kaina", f"{ev_work_cost:.2f} €/metus")

st.caption(
    "Prielaida: papildomas EV krovimas namuose paskirstomas tolygiai per metus ir didina namų elektros poreikį."
)

# ============================================================
# KAUPIKLIO POVEIKIS
# ============================================================

st.markdown("---")
st.header("🔋 Kaupiklio poveikis pasirinktam EV scenarijui")

col1, col2, col3, col4 = st.columns(4)
with col1:
    charge_window = battery_capacity * (1 - battery_min_soc / 100.0)
    st.metric("Naudingas įkrovimo langas", f"{charge_window:.2f} kWh")
with col2:
    st.metric("Į bateriją iš PV", f"{annual_battery_charge:.0f} kWh/metus")
with col3:
    st.metric("Iš baterijos į namą", f"{annual_battery_discharge:.0f} kWh/metus")
with col4:
    st.metric("Kaupiklio nuostoliai", f"{annual_battery_losses:.0f} kWh/metus")

col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("Importas be kaupiklio", f"{annual_import_with_ev_no_battery:.0f} kWh")
with col2:
    st.metric(
        "Importas su kaupikliu",
        f"{annual_import_after_battery:.0f} kWh",
        delta=f"{annual_import_after_battery - annual_import_with_ev_no_battery:.0f} kWh"
    )
with col3:
    st.metric("Atidavimas po kaupiklio", f"{annual_export_after_battery:.0f} kWh")
with col4:
    share_after = annual_onsite_after_battery / annual_total_consumption_with_ev * 100 if annual_total_consumption_with_ev > 0 else 0
    st.metric("Padengta vietoje su kaupikliu", f"{share_after:.1f}%")

# ============================================================
# PLANŲ PALYGINIMAS SU KAUPIKLIU
# ============================================================

st.markdown("---")
st.header("💰 Kurį namų planą rinktis? (su kaupikliu, įskaitant EV krovimą darbe)")

best_total_with_battery = min(total_plan1_with_battery, total_plan2_with_battery, total_plan3_with_battery)
eps = 1e-9

col1, col2, col3 = st.columns(3)

with col1:
    delta1 = total_plan1_with_battery - best_total_with_battery
    is_best1 = abs(delta1) < eps
    st.metric(
        "🏆 Planas 1" if is_best1 else "Planas 1",
        f"{total_plan1_with_battery:.2f} €/metus",
        delta="Geriausias!" if is_best1 else f"+{delta1:.2f} €",
        delta_color="off" if is_best1 else "inverse"
    )
    st.caption(f"Namo plano kaina: {plans_with_battery['plan1_cost']:.2f} €")
    st.caption(f"EV darbe: {ev_work_cost:.2f} €")
    st.caption(f"Metų galo kompensacija: {plans_with_battery['plan1_comp']:.2f} €")

with col2:
    delta2 = total_plan2_with_battery - best_total_with_battery
    is_best2 = abs(delta2) < eps
    st.metric(
        "🏆 Planas 2" if is_best2 else "Planas 2",
        f"{total_plan2_with_battery:.2f} €/metus",
        delta="Geriausias!" if is_best2 else f"+{delta2:.2f} €",
        delta_color="off" if is_best2 else "inverse"
    )
    st.caption(f"Namo plano kaina: {plans_with_battery['plan2_cost']:.2f} €")
    st.caption(f"EV darbe: {ev_work_cost:.2f} €")
    st.caption(f"Fiksuotas mokestis: {plan2_monthly_fee * pv_allowed * 12:.2f} €/metus")

with col3:
    delta3 = total_plan3_with_battery - best_total_with_battery
    is_best3 = abs(delta3) < eps
    st.metric(
        "🏆 Planas 3" if is_best3 else "Planas 3",
        f"{total_plan3_with_battery:.2f} €/metus",
        delta="Geriausias!" if is_best3 else f"+{delta3:.2f} €",
        delta_color="off" if is_best3 else "inverse"
    )
    st.caption(f"Namo plano kaina: {plans_with_battery['plan3_cost']:.2f} €")
    st.caption(f"EV darbe: {ev_work_cost:.2f} €")
    st.caption(f"ESO pasilieka: {plan3_eso_keeps_pct:.0f}%")

# ============================================================
# PAPILDOMAS PALYGINIMAS: BE KAUPIKLIO vs SU KAUPIKLIU
# ============================================================

st.markdown("---")
st.subheader("📌 Tas pats EV scenarijus: be kaupiklio vs su kaupikliu")

col1, col2, col3 = st.columns(3)
with col1:
    saving1 = total_plan1_no_battery - total_plan1_with_battery
    st.metric("Planas 1", f"{total_plan1_with_battery:.2f} €", delta=f"{saving1:.2f} € vs be kaupiklio")
with col2:
    saving2 = total_plan2_no_battery - total_plan2_with_battery
    st.metric("Planas 2", f"{total_plan2_with_battery:.2f} €", delta=f"{saving2:.2f} € vs be kaupiklio")
with col3:
    saving3 = total_plan3_no_battery - total_plan3_with_battery
    st.metric("Planas 3", f"{total_plan3_with_battery:.2f} €", delta=f"{saving3:.2f} € vs be kaupiklio")

# ============================================================
# GRAFIKAI
# ============================================================

st.markdown("---")
st.header("📈 Grafikai")

# 1. Faktiniai mėnesiniai srautai
fig1 = go.Figure()
fig1.add_trace(go.Bar(
    name="Pagamino inverteris",
    x=baseline_disp["Mėnuo"],
    y=baseline_disp["Pagamino inverteris"],
    marker_color="gold"
))
fig1.add_trace(go.Bar(
    name="Atiduota į ESO",
    x=baseline_disp["Mėnuo"],
    y=baseline_disp["Atiduota į ESO"],
    marker_color="orange"
))
fig1.add_trace(go.Bar(
    name="Gauta iš ESO",
    x=baseline_disp["Mėnuo"],
    y=baseline_disp["Gauta iš ESO"],
    marker_color="crimson"
))
fig1.add_trace(go.Scatter(
    name="Bendras vartojimas",
    x=baseline_disp["Mėnuo"],
    y=baseline_disp["Bendras vartojimas"],
    mode="lines+markers",
    line=dict(color="royalblue", width=3)
))
fig1.update_layout(
    title="Istoriniai mėnesiniai energijos srautai",
    barmode="group",
    yaxis_title="kWh",
    height=460
)
st.plotly_chart(fig1, use_container_width=True)

# 2. EV + kaupiklio poveikis importui / eksportui
fig2 = go.Figure()
fig2.add_trace(go.Bar(
    name="Importas be kaupiklio (su EV)",
    x=scenario_with_battery_disp["Mėnuo"],
    y=scenario_with_battery_disp["Gauta iš ESO scenarijui"],
    marker_color="indianred"
))
fig2.add_trace(go.Bar(
    name="Importas su kaupikliu",
    x=scenario_with_battery_disp["Mėnuo"],
    y=scenario_with_battery_disp["Gauta iš ESO po kaupiklio"],
    marker_color="firebrick"
))
fig2.add_trace(go.Bar(
    name="Atidavimas be kaupiklio",
    x=scenario_with_battery_disp["Mėnuo"],
    y=scenario_with_battery_disp["Atiduota į ESO"],
    marker_color="navajowhite"
))
fig2.add_trace(go.Bar(
    name="Atidavimas su kaupikliu",
    x=scenario_with_battery_disp["Mėnuo"],
    y=scenario_with_battery_disp["Atiduota į ESO po kaupiklio"],
    marker_color="goldenrod"
))
fig2.update_layout(
    title="EV + kaupiklio poveikis mėnesiniam importui ir eksportui",
    barmode="group",
    yaxis_title="kWh",
    height=460
)
st.plotly_chart(fig2, use_container_width=True)

# 3. Planų metinė kaina: namų planas ir bendra su EV darbe
fig3 = go.Figure()
fig3.add_trace(go.Bar(
    name="Namo plano kaina su kaupikliu",
    x=["Planas 1", "Planas 2", "Planas 3"],
    y=[
        plans_with_battery["plan1_cost"],
        plans_with_battery["plan2_cost"],
        plans_with_battery["plan3_cost"]
    ],
    marker_color=["#2196F3", "#FF9800", "#4CAF50"]
))
fig3.add_trace(go.Bar(
    name="Bendra kaina + EV darbe",
    x=["Planas 1", "Planas 2", "Planas 3"],
    y=[
        total_plan1_with_battery,
        total_plan2_with_battery,
        total_plan3_with_battery
    ],
    marker_color=["#90CAF9", "#FFCC80", "#A5D6A7"]
))
fig3.update_layout(
    title="Metinė kaina pasirinktam EV scenarijui",
    barmode="group",
    yaxis_title="€",
    height=460
)
st.plotly_chart(fig3, use_container_width=True)

# 4. Kumuliatyvinė kaina su kaupikliu
months1, cum1 = cumulative_cost_series(plans_with_battery["plan1_monthly"], plans_with_battery["plan1_cost"])
months2, cum2 = cumulative_cost_series(plans_with_battery["plan2_monthly"], plans_with_battery["plan2_cost"])
months3, cum3 = cumulative_cost_series(plans_with_battery["plan3_monthly"], plans_with_battery["plan3_cost"])

fig4 = go.Figure()
fig4.add_trace(go.Scatter(
    name="Planas 1",
    x=months1,
    y=cum1,
    mode="lines+markers",
    line=dict(color="#2196F3", width=3)
))
fig4.add_trace(go.Scatter(
    name="Planas 2",
    x=months2,
    y=cum2,
    mode="lines+markers",
    line=dict(color="#FF9800", width=3)
))
fig4.add_trace(go.Scatter(
    name="Planas 3",
    x=months3,
    y=cum3,
    mode="lines+markers",
    line=dict(color="#4CAF50", width=3)
))
fig4.update_layout(
    title="Kumuliatyvinė namo plano kaina per metus (su kaupikliu, be EV darbo kainos)",
    yaxis_title="€",
    height=460
)
st.plotly_chart(fig4, use_container_width=True)

# ============================================================
# JAUTRUMO ANALIZĖ: KIEK KRAUTI DARBE?
# ============================================================

st.markdown("---")
st.header("🔄 Jautrumo analizė: kiek EV krauti darbe?")

sensitivity_rows = []

for wp in range(0, 101, 10):
    work_share = wp / 100.0
    home_share = 1.0 - work_share

    tmp_ev_home = ev_annual_kwh * home_share
    tmp_ev_work = ev_annual_kwh * work_share
    tmp_work_cost = tmp_ev_work * ev_price_work

    tmp_scenario_no_battery = add_ev_home_load(baseline_df, tmp_ev_home)
    tmp_scenario_no_battery = reorder_by_accounting_mode(tmp_scenario_no_battery, accounting_mode)

    tmp_scenario_with_battery = apply_battery_model(
        df_scenario=tmp_scenario_no_battery,
        battery_capacity_kwh=battery_capacity,
        battery_min_soc_pct=battery_min_soc,
        battery_efficiency_pct=battery_efficiency,
        battery_utilization_pct=battery_utilization
    )

    tmp_plan_input = tmp_scenario_with_battery[[
        "Mėn_nr", "Mėnuo", "Atiduota į ESO po kaupiklio", "Gauta iš ESO po kaupiklio"
    ]].rename(columns={
        "Atiduota į ESO po kaupiklio": "Atiduota į ESO",
        "Gauta iš ESO po kaupiklio": "Gauta iš ESO"
    })

    tmp_plans = evaluate_plans(
        plan_df=tmp_plan_input,
        buy_price=buy_price,
        plan1_return_fee=plan1_return_fee,
        plan2_monthly_fee=plan2_monthly_fee,
        plan3_eso_keeps_pct=plan3_eso_keeps_pct,
        compensation_tariff=compensation_tariff,
        pv_allowed=pv_allowed
    )

    sensitivity_rows.append({
        "EV_darbe_%": wp,
        "Planas_1": round(tmp_plans["plan1_cost"] + tmp_work_cost, 2),
        "Planas_2": round(tmp_plans["plan2_cost"] + tmp_work_cost, 2),
        "Planas_3": round(tmp_plans["plan3_cost"] + tmp_work_cost, 2),
    })

df_sens = pd.DataFrame(sensitivity_rows)

fig5 = go.Figure()
fig5.add_trace(go.Scatter(
    name="Planas 1",
    x=df_sens["EV_darbe_%"],
    y=df_sens["Planas_1"],
    mode="lines+markers",
    line=dict(color="#2196F3", width=3)
))
fig5.add_trace(go.Scatter(
    name="Planas 2",
    x=df_sens["EV_darbe_%"],
    y=df_sens["Planas_2"],
    mode="lines+markers",
    line=dict(color="#FF9800", width=3)
))
fig5.add_trace(go.Scatter(
    name="Planas 3",
    x=df_sens["EV_darbe_%"],
    y=df_sens["Planas_3"],
    mode="lines+markers",
    line=dict(color="#4CAF50", width=3)
))
fig5.update_layout(
    title="Bendra metinė kaina priklausomai nuo EV krovimo darbe dalies",
    xaxis_title="EV krovimo darbe dalis (%)",
    yaxis_title="Bendra kaina (€/metus)",
    height=460
)
st.plotly_chart(fig5, use_container_width=True)

st.dataframe(df_sens.set_index("EV_darbe_%"), use_container_width=True)

# ============================================================
# DETALIOS LENTELĖS
# ============================================================

st.markdown("---")
st.header("📋 Detalios lentelės")

with st.expander("📊 Istoriniai baziniai duomenys"):
    st.dataframe(
        baseline_disp.set_index("Mėnuo").drop(columns=["Mėn_nr"]),
        use_container_width=True
    )

with st.expander("🚗 Scenarijus su EV namų krovimu, bet be kaupiklio"):
    st.dataframe(
        scenario_no_battery_disp.set_index("Mėnuo").drop(columns=["Mėn_nr"]),
        use_container_width=True
    )

with st.expander("🔋 Scenarijus su EV ir kaupikliu"):
    st.dataframe(
        scenario_with_battery_disp.set_index("Mėnuo").drop(columns=["Mėn_nr"]),
        use_container_width=True
    )

with st.expander("📘 Planas 1 – be kaupiklio"):
    st.dataframe(plan1_no_battery_disp.set_index("Mėnuo"), use_container_width=True)

with st.expander("📘 Planas 1 – su kaupikliu"):
    st.dataframe(plan1_with_battery_disp.set_index("Mėnuo"), use_container_width=True)

with st.expander("📙 Planas 2 – be kaupiklio"):
    st.dataframe(plan2_no_battery_disp.set_index("Mėnuo"), use_container_width=True)

with st.expander("📙 Planas 2 – su kaupikliu"):
    st.dataframe(plan2_with_battery_disp.set_index("Mėnuo"), use_container_width=True)

with st.expander("📗 Planas 3 – be kaupiklio"):
    st.dataframe(plan3_no_battery_disp.set_index("Mėnuo"), use_container_width=True)

with st.expander("📗 Planas 3 – su kaupikliu"):
    st.dataframe(plan3_with_battery_disp.set_index("Mėnuo"), use_container_width=True)

# ============================================================
# REKOMENDACIJA
# ============================================================

st.markdown("---")
st.header("✅ Rekomendacija")

plans_total = {
    "Planas 1 (Atgavimo mokestis)": total_plan1_with_battery,
    "Planas 2 (Fiksuotas mokestis)": total_plan2_with_battery,
    "Planas 3 (ESO pasilieka %)": total_plan3_with_battery,
}

best_plan = min(plans_total, key=plans_total.get)
best_cost = plans_total[best_plan]
worst_cost = max(plans_total.values())

st.success(
    f"""
### 🏆 Geriausias pasirinkimas tavo pasirinktame EV scenarijuje: **{best_plan}**
**Bendra metinė kaina: {best_cost:.2f} €/metus**

Į šią sumą įeina:
- namų elektros plano kaina su kaupikliu,
- EV krovimo darbe kaina pagal {ev_charge_work_pct:.0f}% darbo krovimo dalį.

Palyginimas:
- Planas 1: **{plans_total['Planas 1 (Atgavimo mokestis)']:.2f} €/metus**
- Planas 2: **{plans_total['Planas 2 (Fiksuotas mokestis)']:.2f} €/metus**
- Planas 3: **{plans_total['Planas 3 (ESO pasilieka %)']:.2f} €/metus**

Skirtumas tarp geriausio ir blogiausio plano: **{worst_cost - best_cost:.2f} €/metus**
"""
)

st.markdown("---")
st.caption(
    "⚠️ Kadangi naudojami mėnesiniai, o ne valandiniai duomenys, EV ir kaupiklio modelis yra orientacinis. "
    "Vis dėlto planų palyginimui jis yra matematiškai nuoseklus ir praktiškai naudingas."
)
st.caption(
    "📌 Jei nori dar tikslesnio modelio, reikėtų valandinių ar bent 15 min. inverterio / namo / EV krovimo duomenų."
)