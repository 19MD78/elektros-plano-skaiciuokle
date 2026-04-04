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
    1: "Sausis", 2: "Vasaris", 3: "Kovas", 4: "Balandis",
    5: "Gegužė", 6: "Birželis", 7: "Liepa", 8: "Rugpjūtis",
    9: "Rugsėjis", 10: "Spalis", 11: "Lapkritis", 12: "Gruodis",
}

DAYS_IN_MONTH = {
    1: 31, 2: 28, 3: 31, 4: 30,
    5: 31, 6: 30, 7: 31, 8: 31,
    9: 30, 10: 31, 11: 30, 12: 31
}

# Numatytieji specifiniai mėnesio generacijos profiliai (kWh/kW)
# Apskaičiuoti iš default duomenų / 14 kW
DEFAULT_MONTHLY_PROFILE_KWH_PER_KW = {
    1: 9.86,   # 138/14
    2: 38.36,  # 537/14
    3: 82.79,  # 1159/14
    4: 127.64, # 1787/14
    5: 139.36, # 1951/14
    6: 164.29, # 2300/14
    7: 134.36, # 1881/14
    8: 125.0,  # 1750/14
    9: 82.64,  # 1157/14
    10: 49.79, # 697/14
    11: 16.07, # 225/14
    12: 7.14,  # 100/14
}

# Numatytieji vartojimo profiliai (proporcijos, suma = 1)
# Apskaičiuoti iš default: momentiškai suvartota = pagamino - atiduota
DEFAULT_DIRECT_PROFILE = {
    1: 78, 2: 177, 3: 241, 4: 225, 5: 295, 6: 718,
    7: 658, 8: 661, 9: 405, 10: 480, 11: 211, 12: 90,
}
DEFAULT_DIRECT_TOTAL = sum(DEFAULT_DIRECT_PROFILE.values())

# Numatytieji importo profiliai
DEFAULT_IMPORT_PROFILE = {
    1: 1104, 2: 1216, 3: 605, 4: 264, 5: 314, 6: 304,
    7: 90, 8: 84, 9: 50, 10: 425, 11: 908, 12: 950,
}
DEFAULT_IMPORT_TOTAL = sum(DEFAULT_IMPORT_PROFILE.values())

# ============================================================
# SIDEBAR
# ============================================================
st.sidebar.header("⚙️ Nustatymai")

# --- Duomenų įvedimo režimas ---
st.sidebar.subheader("📊 Duomenų šaltinis")
data_mode = st.sidebar.radio(
    "Kaip įvesite duomenis?",
    [
        "Įvesti realius mėnesinius duomenis",
        "Skaičiuoti pagal galią ir vartojimą (profilis)"
    ],
    index=0,
    help=(
        "'Realūs mėnesiniai duomenys' – įvedate tikslias kWh reikšmes iš inverterio/ESO.\n"
        "'Profilis' – programa pati apskaičiuoja mėnesinius kiekius pagal galią ir metinius rodiklius."
    )
)

st.sidebar.subheader("🌞 Elektrinės parametrai")
pv_power = st.sidebar.number_input(
    "Elektrinės įrengtoji galia (kW)",
    min_value=0.1,
    value=14.0,
    step=0.5,
    help="Faktinė sumontuotų saulės modulių galia kW."
)

pv_allowed = st.sidebar.number_input(
    "Leistina generuoti galia (kW)",
    min_value=0.1,
    value=10.0,
    step=0.5,
    help="ESO leistina įvesti į tinklą galia. Naudojama Plano 2 fiksuotam mokesčiui skaičiuoti."
)

if pv_allowed > pv_power:
    st.sidebar.warning("⚠️ Leistina generuoti galia didesnė už įrengtąją galią.")

if data_mode == "Skaičiuoti pagal galią ir vartojimą (profilis)":
    st.sidebar.subheader("📐 Metiniai rodikliai (profiliui)")

    annual_generation_input = st.sidebar.number_input(
        "Metinis planuojamas generavimas (kWh/metus)",
        min_value=0.0,
        value=round(pv_power * sum(DEFAULT_MONTHLY_PROFILE_KWH_PER_KW.values()), 0),
        step=100.0,
        help="Arba: specifinė generacija × galia. Pvz. 14 kW × 870 kWh/kW = 12 180 kWh."
    )

    specific_yield_calc = annual_generation_input / pv_power if pv_power > 0 else 0
    st.sidebar.caption(f"Specifinė generacija: **{specific_yield_calc:.0f} kWh/kW/metus**")

    annual_consumption_input = st.sidebar.number_input(
        "Metinis namų elektros poreikis (kWh/metus, be EV)",
        min_value=0.0,
        value=5315.0,
        step=100.0,
        help="Bendras namų vartojimas per metus (be EV krovimo)."
    )

    export_fraction = st.sidebar.slider(
        "Eksporto dalis nuo generacijos (%)",
        min_value=0,
        max_value=100,
        value=72,
        step=1,
        help=(
            "Kiek procentų pagamintos energijos vidutiniškai atiduodama į tinklą. "
            "Likusi dalis suvartojama momentiškai. Pagal istorinius duomenis ~72%."
        )
    )

else:
    st.sidebar.subheader("📐 Metiniai rodikliai (patikrai)")
    declared_direct = st.sidebar.number_input(
        "Momentinis metinis vartojimas / vietoje suvartota (kWh)",
        min_value=0.0,
        value=4239.0,
        step=1.0,
        help="Suma iš inverterio duomenų: Pagamino - Atiduota. Naudojama patikrai."
    )
    declared_total_need = st.sidebar.number_input(
        "Metinis elektros poreikis (kWh)",
        min_value=0.0,
        value=10553.0,
        step=1.0,
        help="Bendras namų vartojimas: momentiškai + importuota. Naudojama patikrai."
    )

# --- Kaupiklis ---
st.sidebar.subheader("🔋 Kaupiklis")
battery_capacity = st.sidebar.number_input(
    "Kaupiklio talpa (kWh)",
    min_value=0.0,
    value=14.4,
    step=0.1,
    help="Nominali kaupiklio talpa kWh. Įveskite 0 jei kaupiklio nėra."
)
battery_min_soc = st.sidebar.number_input(
    "Min. SOC (%)",
    min_value=0.0,
    max_value=100.0,
    value=20.0,
    step=5.0,
    help="Minimali leistina baterijos įkrova procentais."
)
battery_efficiency = st.sidebar.number_input(
    "Kaupiklio efektyvumas (%)",
    min_value=1.0,
    max_value=100.0,
    value=90.0,
    step=1.0,
    help="Apvaliojo ciklo efektyvumas (charge × discharge)."
)
battery_utilization = st.sidebar.number_input(
    "Kaupiklio panaudojimo koeficientas (%)",
    min_value=0.0,
    max_value=100.0,
    value=100.0,
    step=5.0,
    help=(
        "Konservatyvumo koeficientas. 100% = teorinis maksimumas. "
        "Rekomenduojama 70–80% dėl mėnesinių (ne valandinių) duomenų."
    )
)

# --- EV ---
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
    step=5,
    help="0% = viskas kraunama namuose, 100% = viskas kraunama darbe."
)
ev_price_work = st.sidebar.number_input(
    "EV krovimo kaina darbe (€/kWh)",
    min_value=0.0,
    value=0.13,
    step=0.01,
    format="%.4f"
)

# --- Apskaita ---
st.sidebar.subheader("📅 Apskaitos tvarka")
accounting_mode = st.sidebar.selectbox(
    "Mėnesių eiliškumas planams",
    [
        "Balandis–Kovas (ESO kaupimo ciklas)",
        "Sausis–Gruodis (kalendoriniai metai)"
    ],
    index=0
)

# --- Tarifai ---
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
    format="%.4f",
    help="Mokestis už kiekvieno atsiimto kWh perdavimą. Pvz. ESO paslaugos mokestis."
)
plan2_monthly_fee = st.sidebar.number_input(
    "Planas 2: mokestis už kW per mėn. (€/kW/mėn.)",
    min_value=0.0,
    value=5.0336,
    step=0.1,
    format="%.4f",
    help=f"Fiksuotas mėnesinis mokestis už leistinos galios kW. Metinis: {5.0336 * 10.0 * 12:.2f} € (10 kW pvz.)"
)
plan3_eso_keeps_pct = st.sidebar.number_input(
    "Planas 3: ESO pasilieka (%)",
    min_value=0.0,
    max_value=100.0,
    value=37.0,
    step=1.0,
    help="Procentas eksportuotos energijos, kurią ESO pasilieka kaip mokestį. Likusi dalis grąžinama į banką."
)
compensation_tariff = st.sidebar.number_input(
    "Metų pabaigos kompensacijos tarifas (€/kWh)",
    min_value=0.0,
    value=0.01,
    step=0.005,
    format="%.4f",
    help="Tarif, kuriuo apmokamas metų pabaigoje likęs nepanaudotas banko likutis."
)

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
            f"Šiuose mėnesiuose 'Atiduota į ESO' > 'Pagamino inverteris': {', '.join(bad_months)}."
        )
        st.stop()

    df["Mėn_nr"] = df["Mėn_nr"].astype(int)
    return df


def build_profile_based_df(
    pv_power_kw: float,
    annual_generation_kwh: float,
    annual_consumption_kwh: float,
    export_fraction_pct: int
) -> pd.DataFrame:
    """
    Generuoja mėnesinius duomenis pagal profilius ir vartotojo įvestus metinius rodiklius.
    """
    # Generacija pagal mėnesio profilį
    profile_gen_total = sum(DEFAULT_MONTHLY_PROFILE_KWH_PER_KW.values())
    
    rows = []
    for m in range(1, 13):
        # Mėnesio generacija
        month_gen_fraction = DEFAULT_MONTHLY_PROFILE_KWH_PER_KW[m] / profile_gen_total
        month_generation = annual_generation_kwh * month_gen_fraction

        # Eksportas = generacija × eksporto frakcija
        month_export = month_generation * (export_fraction_pct / 100.0)
        # Momentinis vartojimas iš PV
        month_direct = month_generation - month_export

        # Importas pagal vartojimo profilį
        direct_fraction = DEFAULT_DIRECT_PROFILE[m] / DEFAULT_DIRECT_TOTAL
        import_fraction = DEFAULT_IMPORT_PROFILE[m] / DEFAULT_IMPORT_TOTAL

        # Bendras mėnesio vartojimas
        month_total_consumption = annual_consumption_kwh * (
            (direct_fraction + import_fraction) / 2
        )
        # Importas = bendras vartojimas - momentiškai suvartota
        month_import = max(0.0, month_total_consumption - month_direct)

        # Tiksliau: importas pagal importo profilį, proporcingas metiniam importui
        estimated_annual_import = annual_consumption_kwh - (annual_generation_kwh * (1 - export_fraction_pct / 100.0))
        if estimated_annual_import < 0:
            estimated_annual_import = 0.0
        month_import = estimated_annual_import * (DEFAULT_IMPORT_PROFILE[m] / DEFAULT_IMPORT_TOTAL)

        rows.append({
            "Mėn_nr": m,
            "Mėnuo": MONTH_NAMES_LT[m],
            "Pagamino inverteris": round(month_generation, 1),
            "Atiduota į ESO": round(month_export, 1),
            "Gauta iš ESO": round(month_import, 1),
        })

    df = pd.DataFrame(rows)

    # Validacija: atiduota negali viršyti pagaminto
    df["Atiduota į ESO"] = df.apply(
        lambda r: min(r["Atiduota į ESO"], r["Pagamino inverteris"]), axis=1
    )
    return df


def reorder_by_accounting_mode(df: pd.DataFrame, accounting_mode: str) -> pd.DataFrame:
    if accounting_mode == "Balandis–Kovas (ESO kaupimo ciklas)":
        order = [4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2, 3]
    else:
        order = list(range(1, 13))

    order_map = {m: i for i, m in enumerate(order)}
    out = df.copy()
    out["sort_order"] = out["Mėn_nr"].map(order_map)
    out = out.sort_values("sort_order").drop(columns=["sort_order"]).reset_index(drop=True)
    return out


def build_baseline_energy_df(df_input: pd.DataFrame) -> pd.DataFrame:
    df = df_input.copy()
    df["Momentiškai suvartota"] = df["Pagamino inverteris"] - df["Atiduota į ESO"]
    df["Bendras vartojimas"] = df["Momentiškai suvartota"] + df["Gauta iš ESO"]
    df["Mėnesio balansas"] = df["Atiduota į ESO"] - df["Gauta iš ESO"]
    return df


def add_ev_home_load(df_base: pd.DataFrame, ev_home_kwh_annual: float) -> pd.DataFrame:
    """
    Papildomas EV krovimas namuose – tolygiai paskirstomas per 12 mėn.
    """
    df = df_base.copy()
    ev_home_monthly = ev_home_kwh_annual / 12.0
    df["EV namuose"] = ev_home_monthly
    df["Gauta iš ESO be kaupiklio (su EV)"] = df["Gauta iš ESO"] + ev_home_monthly
    df["Bendras vartojimas su EV"] = df["Bendras vartojimas"] + ev_home_monthly
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
    df = df_scenario.copy()

    if battery_capacity_kwh <= 0 or battery_efficiency_pct <= 0 or battery_utilization_pct <= 0:
        df["Į bateriją iš PV"] = 0.0
        df["Iš baterijos į namą"] = 0.0
        df["Kaupiklio nuostoliai"] = 0.0
        df["Atiduota į ESO po kaupiklio"] = df["Atiduota į ESO"]
        df["Gauta iš ESO po kaupiklio"] = df["Gauta iš ESO scenarijui"]
        df["Bendra vietoje padengta po kaupiklio"] = df["Momentiškai suvartota"]
        df["Vietoje padengta dalis po kaupiklio %"] = (
            df["Momentiškai suvartota"] / df["Bendras vartojimas scenarijui"] * 100
        ).fillna(0)
        return df

    charge_window = battery_capacity_kwh * (1 - battery_min_soc_pct / 100.0)
    roundtrip_eff = battery_efficiency_pct / 100.0
    utilization = battery_utilization_pct / 100.0

    results = {
        "Į bateriją iš PV": [],
        "Iš baterijos į namą": [],
        "Kaupiklio nuostoliai": [],
        "Atiduota į ESO po kaupiklio": [],
        "Gauta iš ESO po kaupiklio": [],
        "Bendra vietoje padengta po kaupiklio": [],
        "Vietoje padengta dalis po kaupiklio %": [],
    }

    for _, row in df.iterrows():
        month = int(row["Mėn_nr"])
        days = DAYS_IN_MONTH[month]

        exported = float(row["Atiduota į ESO"])
        imported = float(row["Gauta iš ESO scenarijui"])
        direct_onsite = float(row["Momentiškai suvartota"])
        total_consumption = float(row["Bendras vartojimas scenarijui"])

        daily_export = exported / days
        daily_import = imported / days

        daily_battery_to_home = min(
            daily_import,
            daily_export * roundtrip_eff,
            charge_window * roundtrip_eff
        ) * utilization

        monthly_battery_to_home = daily_battery_to_home * days
        monthly_pv_to_battery = (monthly_battery_to_home / roundtrip_eff) if roundtrip_eff > 0 else 0.0
        monthly_pv_to_battery = min(monthly_pv_to_battery, exported)
        monthly_battery_to_home = min(monthly_battery_to_home, imported)

        battery_losses = monthly_pv_to_battery - monthly_battery_to_home
        export_after = max(0.0, exported - monthly_pv_to_battery)
        import_after = max(0.0, imported - monthly_battery_to_home)
        onsite_after = direct_onsite + monthly_battery_to_home
        onsite_share = (onsite_after / total_consumption * 100) if total_consumption > 0 else 0.0

        results["Į bateriją iš PV"].append(monthly_pv_to_battery)
        results["Iš baterijos į namą"].append(monthly_battery_to_home)
        results["Kaupiklio nuostoliai"].append(battery_losses)
        results["Atiduota į ESO po kaupiklio"].append(export_after)
        results["Gauta iš ESO po kaupiklio"].append(import_after)
        results["Bendra vietoje padengta po kaupiklio"].append(onsite_after)
        results["Vietoje padengta dalis po kaupiklio %"].append(onsite_share)

    for col, vals in results.items():
        df[col] = vals

    return df


def calculate_plan1(df, buy_price, return_fee, compensation_tariff):
    bank = 0.0
    total_cost = 0.0
    rows = []
    for _, row in df.iterrows():
        exported = float(row["Atiduota į ESO"])
        imported = float(row["Gauta iš ESO"])
        available = bank + exported
        retrieved = min(imported, available)
        bought = imported - retrieved
        bank = available - retrieved
        retrieval_cost = retrieved * return_fee
        purchase_cost = bought * buy_price
        month_cost = retrieval_cost + purchase_cost
        total_cost += month_cost
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
    return total_cost - compensation, pd.DataFrame(rows), bank, compensation


def calculate_plan2(df, buy_price, monthly_fee_per_kw, compensation_tariff, pv_allowed):
    bank = 0.0
    total_cost = 0.0
    fixed_monthly_fee = monthly_fee_per_kw * pv_allowed
    rows = []
    for _, row in df.iterrows():
        exported = float(row["Atiduota į ESO"])
        imported = float(row["Gauta iš ESO"])
        available = bank + exported
        retrieved = min(imported, available)
        bought = imported - retrieved
        bank = available - retrieved
        purchase_cost = bought * buy_price
        month_cost = fixed_monthly_fee + purchase_cost
        total_cost += month_cost
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
    return total_cost - compensation, pd.DataFrame(rows), bank, compensation


def calculate_plan3(df, buy_price, eso_keeps_pct, compensation_tariff):
    bank = 0.0
    total_cost = 0.0
    eso_return_pct = (100.0 - eso_keeps_pct) / 100.0
    rows = []
    for _, row in df.iterrows():
        exported = float(row["Atiduota į ESO"])
        imported = float(row["Gauta iš ESO"])
        effective_export = exported * eso_return_pct
        eso_kept = exported - effective_export
        available = bank + effective_export
        retrieved = min(imported, available)
        bought = imported - retrieved
        bank = available - retrieved
        purchase_cost = bought * buy_price
        month_cost = purchase_cost
        total_cost += month_cost
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
    return total_cost - compensation, pd.DataFrame(rows), bank, compensation


def evaluate_plans(plan_df, buy_price, plan1_return_fee, plan2_monthly_fee,
                   plan3_eso_keeps_pct, compensation_tariff, pv_allowed):
    p1_cost, p1_monthly, p1_left, p1_comp = calculate_plan1(
        plan_df, buy_price, plan1_return_fee, compensation_tariff)
    p2_cost, p2_monthly, p2_left, p2_comp = calculate_plan2(
        plan_df, buy_price, plan2_monthly_fee, compensation_tariff, pv_allowed)
    p3_cost, p3_monthly, p3_left, p3_comp = calculate_plan3(
        plan_df, buy_price, plan3_eso_keeps_pct, compensation_tariff)
    return {
        "plan1_cost": p1_cost, "plan2_cost": p2_cost, "plan3_cost": p3_cost,
        "plan1_monthly": p1_monthly, "plan2_monthly": p2_monthly, "plan3_monthly": p3_monthly,
        "plan1_left": p1_left, "plan2_left": p2_left, "plan3_left": p3_left,
        "plan1_comp": p1_comp, "plan2_comp": p2_comp, "plan3_comp": p3_comp,
    }


def round_display_df(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in out.columns:
        if pd.api.types.is_numeric_dtype(out[col]):
            if any(k in col.lower() for k in ["kaina", "mokestis", "kompensacija"]):
                out[col] = out[col].round(2)
            else:
                out[col] = out[col].round(1)
    return out


def cumulative_cost_series(plan_df, final_total_cost):
    months = plan_df["Mėnuo"].tolist()
    cum = plan_df["Mėn. kaina"].cumsum().tolist()
    return months + ["Metų pabaiga"], cum + [final_total_cost]


# ============================================================
# DUOMENŲ RUOŠIMAS
# ============================================================

DEFAULT_MONTHLY_DATA = pd.DataFrame({
    "Mėn_nr": list(range(1, 13)),
    "Mėnuo": [MONTH_NAMES_LT[i] for i in range(1, 13)],
    "Pagamino inverteris": [138, 537, 1159, 1787, 1951, 2300, 1881, 1750, 1157, 697, 225, 100],
    "Atiduota į ESO":      [60,  360,  918, 1562, 1656, 1582, 1223, 1089,  752, 217,  14,  10],
    "Gauta iš ESO":       [1104, 1216,  605,  264,  314,  304,   90,   84,   50, 425, 908, 950],
})

st.markdown("---")

if data_mode == "Įvesti realius mėnesinius duomenis":
    st.header("📥 Realūs mėnesiniai duomenys")
    st.markdown(
        "Įveskite tikslias reikšmes iš inverterio ir ESO ataskaitos. "
        "Galite redaguoti stulpelius **Pagamino inverteris**, **Atiduota į ESO**, **Gauta iš ESO**."
    )

    edited_data = st.data_editor(
        DEFAULT_MONTHLY_DATA,
        hide_index=True,
        use_container_width=True,
        num_rows="fixed",
        disabled=["Mėn_nr", "Mėnuo"],
        column_config={
            "Pagamino inverteris": st.column_config.NumberColumn(
                "Pagamino inverteris (kWh)", min_value=0, format="%.1f"
            ),
            "Atiduota į ESO": st.column_config.NumberColumn(
                "Atiduota į ESO (kWh)", min_value=0, format="%.1f"
            ),
            "Gauta iš ESO": st.column_config.NumberColumn(
                "Gauta iš ESO (kWh)", min_value=0, format="%.1f"
            ),
        }
    )
    raw_df = clean_and_validate_input(edited_data)

else:
    st.header("📐 Profilio pagrindu apskaičiuoti duomenys")
    st.info(
        "Duomenys apskaičiuoti automatiškai pagal įrengtą galią, metinį generavimą ir vartojimą. "
        "Jei norite tikslesnių rezultatų – pasirinkite 'Įvesti realius mėnesinius duomenis'."
    )
    profile_df = build_profile_based_df(
        pv_power_kw=pv_power,
        annual_generation_kwh=annual_generation_input,
        annual_consumption_kwh=annual_consumption_input,
        export_fraction_pct=export_fraction
    )
    st.dataframe(profile_df, hide_index=True, use_container_width=True)
    raw_df = clean_and_validate_input(profile_df)

# ============================================================
# BAZINIS SCENARIJUS
# ============================================================
baseline_df = build_baseline_energy_df(raw_df)

annual_generated    = baseline_df["Pagamino inverteris"].sum()
annual_exported     = baseline_df["Atiduota į ESO"].sum()
annual_imported     = baseline_df["Gauta iš ESO"].sum()
annual_direct       = baseline_df["Momentiškai suvartota"].sum()
annual_total_consumption = baseline_df["Bendras vartojimas"].sum()

# ============================================================
# EV SKAIČIAVIMAS
# ============================================================
ev_annual_kwh  = ev_km_per_year * ev_consumption / 100.0
ev_work_share  = ev_charge_work_pct / 100.0
ev_home_share  = 1.0 - ev_work_share
ev_home_kwh    = ev_annual_kwh * ev_home_share
ev_work_kwh    = ev_annual_kwh * ev_work_share
ev_work_cost   = ev_work_kwh * ev_price_work

# Scenarijai
scenario_no_battery_df = add_ev_home_load(baseline_df, ev_home_kwh)
scenario_no_battery_df = reorder_by_accounting_mode(scenario_no_battery_df, accounting_mode)

scenario_with_battery_df = apply_battery_model(
    df_scenario=scenario_no_battery_df,
    battery_capacity_kwh=battery_capacity,
    battery_min_soc_pct=battery_min_soc,
    battery_efficiency_pct=battery_efficiency,
    battery_utilization_pct=battery_utilization
)

# ============================================================
# PLANŲ ĮVESTIES DF
# ============================================================
plan_input_no_battery = scenario_no_battery_df[
    ["Mėn_nr", "Mėnuo", "Atiduota į ESO", "Gauta iš ESO scenarijui"]
].rename(columns={"Gauta iš ESO scenarijui": "Gauta iš ESO"})

plan_input_with_battery = scenario_with_battery_df[
    ["Mėn_nr", "Mėnuo", "Atiduota į ESO po kaupiklio", "Gauta iš ESO po kaupiklio"]
].rename(columns={
    "Atiduota į ESO po kaupiklio": "Atiduota į ESO",
    "Gauta iš ESO po kaupiklio":   "Gauta iš ESO"
})

plans_no_battery   = evaluate_plans(
    plan_input_no_battery, buy_price, plan1_return_fee,
    plan2_monthly_fee, plan3_eso_keeps_pct, compensation_tariff, pv_allowed
)
plans_with_battery = evaluate_plans(
    plan_input_with_battery, buy_price, plan1_return_fee,
    plan2_monthly_fee, plan3_eso_keeps_pct, compensation_tariff, pv_allowed
)

# Galutinės bendros metinės kainos
total_plan1_no_battery   = plans_no_battery["plan1_cost"]   + ev_work_cost
total_plan2_no_battery   = plans_no_battery["plan2_cost"]   + ev_work_cost
total_plan3_no_battery   = plans_no_battery["plan3_cost"]   + ev_work_cost
total_plan1_with_battery = plans_with_battery["plan1_cost"] + ev_work_cost
total_plan2_with_battery = plans_with_battery["plan2_cost"] + ev_work_cost
total_plan3_with_battery = plans_with_battery["plan3_cost"] + ev_work_cost

# ============================================================
# SUVESTINĖS REIKŠMĖS
# ============================================================
annual_ev_home_added              = scenario_no_battery_df["EV namuose"].sum()
annual_total_consumption_with_ev  = scenario_no_battery_df["Bendras vartojimas scenarijui"].sum()
annual_import_with_ev_no_battery  = scenario_no_battery_df["Gauta iš ESO scenarijui"].sum()

annual_battery_charge      = scenario_with_battery_df["Į bateriją iš PV"].sum()
annual_battery_discharge   = scenario_with_battery_df["Iš baterijos į namą"].sum()
annual_battery_losses      = scenario_with_battery_df["Kaupiklio nuostoliai"].sum()
annual_export_after_battery = scenario_with_battery_df["Atiduota į ESO po kaupiklio"].sum()
annual_import_after_battery = scenario_with_battery_df["Gauta iš ESO po kaupiklio"].sum()
annual_onsite_after_battery = scenario_with_battery_df["Bendra vietoje padengta po kaupiklio"].sum()

# Display DF
baseline_disp              = round_display_df(reorder_by_accounting_mode(baseline_df, accounting_mode))
scenario_no_battery_disp   = round_display_df(scenario_no_battery_df)
scenario_with_battery_disp = round_display_df(scenario_with_battery_df)

plan1_no_battery_disp   = round_display_df(plans_no_battery["plan1_monthly"])
plan2_no_battery_disp   = round_display_df(plans_no_battery["plan2_monthly"])
plan3_no_battery_disp   = round_display_df(plans_no_battery["plan3_monthly"])
plan1_with_battery_disp = round_display_df(plans_with_battery["plan1_monthly"])
plan2_with_battery_disp = round_display_df(plans_with_battery["plan2_monthly"])
plan3_with_battery_disp = round_display_df(plans_with_battery["plan3_monthly"])

# ============================================================
# REZULTATAI
# ============================================================
st.markdown("---")
st.header("📊 Faktinių duomenų suvestinė")

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
    st.metric("Bendras vartojimas (be EV)", f"{annual_total_consumption:.0f} kWh")
with col2:
    specific_yield = annual_generated / pv_power if pv_power > 0 else 0.0
    st.metric("Specifinė generacija", f"{specific_yield:.0f} kWh/kW")
with col3:
    base_self_share = (
        annual_direct / annual_total_consumption * 100
        if annual_total_consumption > 0 else 0
    )
    st.metric("Padengta vietoje (be kaupiklio)", f"{base_self_share:.1f}%")
with col4:
    st.metric("Eksporto–importo balansas", f"{annual_exported - annual_imported:.0f} kWh")

# Patikra tik realių duomenų režimu
if data_mode == "Įvesti realius mėnesinius duomenis":
    st.markdown("---")
    st.subheader("🔎 Metinių skaičių patikra su deklaruotais rodikliais")
    direct_diff = annual_direct - declared_direct
    need_diff   = annual_total_consumption - declared_total_need
    col1, col2 = st.columns(2)
    with col1:
        st.metric(
            "Deklaruotas momentinis vartojimas",
            f"{declared_direct:.0f} kWh",
            delta=f"{direct_diff:+.0f} kWh vs mėnesių suma"
        )
    with col2:
        st.metric(
            "Deklaruotas metinis poreikis",
            f"{declared_total_need:.0f} kWh",
            delta=f"{need_diff:+.0f} kWh vs mėnesių suma"
        )
    if abs(direct_diff) < 0.5 and abs(need_diff) < 0.5:
        st.success("✅ Mėnesiniai duomenys tiksliai sutampa su deklaruotais metiniais skaičiais.")
    else:
        st.warning("⚠️ Yra neatitikimas tarp deklaruotų metinių dydžių ir sumos iš mėnesių.")

st.info(
    "**Formulės:**\n"
    "- Momentiškai suvartota = Pagamino inverteris − Atiduota į ESO\n"
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
    st.metric(
        "EV kraunama namuose",
        f"{ev_home_kwh:.0f} kWh",
        delta=f"{ev_home_share * 100:.0f}% viso EV poreikio"
    )
with col3:
    st.metric(
        "EV kraunama darbe",
        f"{ev_work_kwh:.0f} kWh",
        delta=f"{ev_work_share * 100:.0f}% viso EV poreikio"
    )
with col4:
    st.metric("EV krovimo darbe kaina", f"{ev_work_cost:.2f} €/metus")

st.caption(
    "Prielaida: EV krovimas namuose paskirstomas tolygiai per metus ir didina namų importo poreikį."
)

# ============================================================
# KAUPIKLIO POVEIKIS
# ============================================================
st.markdown("---")
st.header("🔋 Kaupiklio poveikis")

charge_window = battery_capacity * (1 - battery_min_soc / 100.0)
col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("Naudingas įkrovimo langas", f"{charge_window:.2f} kWh")
with col2:
    st.metric("Į bateriją iš PV (metinis)", f"{annual_battery_charge:.0f} kWh")
with col3:
    st.metric("Iš baterijos į namą (metinis)", f"{annual_battery_discharge:.0f} kWh")
with col4:
    st.metric("Kaupiklio nuostoliai (metiniai)", f"{annual_battery_losses:.0f} kWh")

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
    st.metric("Eksportas po kaupiklio", f"{annual_export_after_battery:.0f} kWh")
with col4:
    share_after = (
        annual_onsite_after_battery / annual_total_consumption_with_ev * 100
        if annual_total_consumption_with_ev > 0 else 0
    )
    st.metric("Padengta vietoje su kaupikliu", f"{share_after:.1f}%")

# ============================================================
# PLANŲ PALYGINIMAS SU KAUPIKLIU
# ============================================================
st.markdown("---")
st.header("💰 Planų palyginimas su kaupikliu (įskaitant EV krovimą darbe)")

best_total = min(total_plan1_with_battery, total_plan2_with_battery, total_plan3_with_battery)
eps = 1e-9

col1, col2, col3 = st.columns(3)
for col, label, total, plan_key, extra_caption in [
    (col1, "Planas 1", total_plan1_with_battery, "plan1",
     f"Atsiėmimo mokestis: {plan1_return_fee:.4f} €/kWh"),
    (col2, "Planas 2", total_plan2_with_battery, "plan2",
     f"Fiksuotas: {plan2_monthly_fee * pv_allowed * 12:.2f} €/metus"),
    (col3, "Planas 3", total_plan3_with_battery, "plan3",
     f"ESO pasilieka: {plan3_eso_keeps_pct:.0f}%"),
]:
    with col:
        delta_val = total - best_total
        is_best = abs(delta_val) < eps
        st.metric(
            f"🏆 {label}" if is_best else label,
            f"{total:.2f} €/metus",
            delta="Geriausias!" if is_best else f"+{delta_val:.2f} €",
            delta_color="off" if is_best else "inverse"
        )
        st.caption(f"Namo plano kaina: {plans_with_battery[f'{plan_key}_cost']:.2f} €")
        st.caption(f"EV krovimas darbe: {ev_work_cost:.2f} €")
        st.caption(f"Metų galo kompensacija: {plans_with_battery[f'{plan_key}_comp']:.2f} €")
        st.caption(extra_caption)

# ============================================================
# BE KAUPIKLIO vs SU KAUPIKLIU
# ============================================================
st.markdown("---")
st.subheader("📌 Be kaupiklio vs su kaupikliu (tas pats EV scenarijus)")

col1, col2, col3 = st.columns(3)
for col, label, total_with, total_without in [
    (col1, "Planas 1", total_plan1_with_battery, total_plan1_no_battery),
    (col2, "Planas 2", total_plan2_with_battery, total_plan2_no_battery),
    (col3, "Planas 3", total_plan3_with_battery, total_plan3_no_battery),
]:
    with col:
        saving = total_without - total_with
        st.metric(
            label,
            f"{total_with:.2f} € (su kaupikliu)",
            delta=f"{saving:+.2f} € taupymas vs be kaupiklio"
        )

# ============================================================
# GRAFIKAI
# ============================================================
st.markdown("---")
st.header("📈 Grafikai")

# 1. Mėnesiniai energijos srautai
fig1 = go.Figure()
fig1.add_trace(go.Bar(
    name="Pagamino inverteris", x=baseline_disp["Mėnuo"],
    y=baseline_disp["Pagamino inverteris"], marker_color="gold"
))
fig1.add_trace(go.Bar(
    name="Atiduota į ESO", x=baseline_disp["Mėnuo"],
    y=baseline_disp["Atiduota į ESO"], marker_color="orange"
))
fig1.add_trace(go.Bar(
    name="Gauta iš ESO", x=baseline_disp["Mėnuo"],
    y=baseline_disp["Gauta iš ESO"], marker_color="crimson"
))
fig1.add_trace(go.Scatter(
    name="Bendras vartojimas", x=baseline_disp["Mėnuo"],
    y=baseline_disp["Bendras vartojimas"],
    mode="lines+markers", line=dict(color="royalblue", width=3)
))
fig1.update_layout(
    title="Istoriniai mėnesiniai energijos srautai",
    barmode="group", yaxis_title="kWh", height=460
)
st.plotly_chart(fig1, use_container_width=True)

# 2. Kaupiklio poveikis
fig2 = go.Figure()
fig2.add_trace(go.Bar(
    name="Importas be kaupiklio (su EV)", x=scenario_with_battery_disp["Mėnuo"],
    y=scenario_with_battery_disp["Gauta iš ESO scenarijui"], marker_color="indianred"
))
fig2.add_trace(go.Bar(
    name="Importas su kaupikliu", x=scenario_with_battery_disp["Mėnuo"],
    y=scenario_with_battery_disp["Gauta iš ESO po kaupiklio"], marker_color="firebrick"
))
fig2.add_trace(go.Bar(
    name="Eksportas be kaupiklio", x=scenario_with_battery_disp["Mėnuo"],
    y=scenario_with_battery_disp["Atiduota į ESO"], marker_color="navajowhite"
))
fig2.add_trace(go.Bar(
    name="Eksportas su kaupikliu", x=scenario_with_battery_disp["Mėnuo"],
    y=scenario_with_battery_disp["Atiduota į ESO po kaupiklio"], marker_color="goldenrod"
))
fig2.update_layout(
    title="EV + kaupiklio poveikis mėnesiniam importui ir eksportui",
    barmode="group", yaxis_title="kWh", height=460
)
st.plotly_chart(fig2, use_container_width=True)

# 3. Metinė kaina planams
fig3 = go.Figure()
plan_labels = ["Planas 1", "Planas 2", "Planas 3"]
colors_dark  = ["#2196F3", "#FF9800", "#4CAF50"]
colors_light = ["#90CAF9", "#FFCC80", "#A5D6A7"]

fig3.add_trace(go.Bar(
    name="Namo plano kaina su kaupikliu", x=plan_labels,
    y=[plans_with_battery["plan1_cost"], plans_with_battery["plan2_cost"], plans_with_battery["plan3_cost"]],
    marker_color=colors_dark
))
fig3.add_trace(go.Bar(
    name="Bendra kaina + EV darbe", x=plan_labels,
    y=[total_plan1_with_battery, total_plan2_with_battery, total_plan3_with_battery],
    marker_color=colors_light
))
fig3.update_layout(
    title="Metinė kaina (su kaupikliu, įskaitant EV darbe)",
    barmode="group", yaxis_title="€", height=460
)
st.plotly_chart(fig3, use_container_width=True)

# 4. Kumuliatyvinė kaina
months1, cum1 = cumulative_cost_series(plans_with_battery["plan1_monthly"], plans_with_battery["plan1_cost"])
months2, cum2 = cumulative_cost_series(plans_with_battery["plan2_monthly"], plans_with_battery["plan2_cost"])
months3, cum3 = cumulative_cost_series(plans_with_battery["plan3_monthly"], plans_with_battery["plan3_cost"])

fig4 = go.Figure()
for months, cum, name, color in [
    (months1, cum1, "Planas 1", "#2196F3"),
    (months2, cum2, "Planas 2", "#FF9800"),
    (months3, cum3, "Planas 3", "#4CAF50"),
]:
    fig4.add_trace(go.Scatter(
        name=name, x=months, y=cum,
        mode="lines+markers", line=dict(color=color, width=3)
    ))
fig4.update_layout(
    title="Kumuliatyvinė namo plano kaina per metus (su kaupikliu, be EV darbo kainos)",
    yaxis_title="€", height=460
)
st.plotly_chart(fig4, use_container_width=True)

# ============================================================
# JAUTRUMO ANALIZĖ
# ============================================================
st.markdown("---")
st.header("🔄 Jautrumo analizė: kiek EV krauti darbe?")

sensitivity_rows = []
for wp in range(0, 101, 10):
    tmp_home_kwh = ev_annual_kwh * (1 - wp / 100.0)
    tmp_work_kwh = ev_annual_kwh * (wp / 100.0)
    tmp_work_cost = tmp_work_kwh * ev_price_work

    tmp_scen = add_ev_home_load(baseline_df, tmp_home_kwh)
    tmp_scen = reorder_by_accounting_mode(tmp_scen, accounting_mode)
    tmp_scen_bat = apply_battery_model(
        tmp_scen, battery_capacity, battery_min_soc, battery_efficiency, battery_utilization
    )
    tmp_plan_input = tmp_scen_bat[
        ["Mėn_nr", "Mėnuo", "Atiduota į ESO po kaupiklio", "Gauta iš ESO po kaupiklio"]
    ].rename(columns={
        "Atiduota į ESO po kaupiklio": "Atiduota į ESO",
        "Gauta iš ESO po kaupiklio":   "Gauta iš ESO"
    })
    tmp_plans = evaluate_plans(
        tmp_plan_input, buy_price, plan1_return_fee,
        plan2_monthly_fee, plan3_eso_keeps_pct, compensation_tariff, pv_allowed
    )
    sensitivity_rows.append({
        "EV darbe (%)": wp,
        "Planas 1 (€)": round(tmp_plans["plan1_cost"] + tmp_work_cost, 2),
        "Planas 2 (€)": round(tmp_plans["plan2_cost"] + tmp_work_cost, 2),
        "Planas 3 (€)": round(tmp_plans["plan3_cost"] + tmp_work_cost, 2),
    })

df_sens = pd.DataFrame(sensitivity_rows)

fig5 = go.Figure()
for col_name, color in [
    ("Planas 1 (€)", "#2196F3"),
    ("Planas 2 (€)", "#FF9800"),
    ("Planas 3 (€)", "#4CAF50"),
]:
    fig5.add_trace(go.Scatter(
        name=col_name.replace(" (€)", ""),
        x=df_sens["EV darbe (%)"],
        y=df_sens[col_name],
        mode="lines+markers",
        line=dict(color=color, width=3)
    ))
fig5.update_layout(
    title="Bendra metinė kaina priklausomai nuo EV krovimo darbe dalies",
    xaxis_title="EV krovimo darbe dalis (%)",
    yaxis_title="Bendra kaina (€/metus)",
    height=460
)
st.plotly_chart(fig5, use_container_width=True)
st.dataframe(df_sens.set_index("EV darbe (%)"), use_container_width=True)

# ============================================================
# DETALIOS LENTELĖS
# ============================================================
st.markdown("---")
st.header("📋 Detalios lentelės")

with st.expander("📊 Baziniai duomenys"):
    st.dataframe(
        baseline_disp.set_index("Mėnuo").drop(columns=["Mėn_nr"]),
        use_container_width=True
    )

with st.expander("🚗 Scenarijus su EV namų krovimu (be kaupiklio)"):
    st.dataframe(
        scenario_no_battery_disp.set_index("Mėnuo").drop(columns=["Mėn_nr"]),
        use_container_width=True
    )

with st.expander("🔋 Scenarijus su EV ir kaupikliu"):
    st.dataframe(
        scenario_with_battery_disp.set_index("Mėnuo").drop(columns=["Mėn_nr"]),
        use_container_width=True
    )

for label, disp_nb, disp_wb in [
    ("📘 Planas 1", plan1_no_battery_disp, plan1_with_battery_disp),
    ("📙 Planas 2", plan2_no_battery_disp, plan2_with_battery_disp),
    ("📗 Planas 3", plan3_no_battery_disp, plan3_with_battery_disp),
]:
    with st.expander(f"{label} – be kaupiklio"):
        st.dataframe(disp_nb.set_index("Mėnuo"), use_container_width=True)
    with st.expander(f"{label} – su kaupikliu"):
        st.dataframe(disp_wb.set_index("Mėnuo"), use_container_width=True)

# ============================================================
# REKOMENDACIJA
# ============================================================
st.markdown("---")
st.header("✅ Rekomendacija")

plans_total = {
    "Planas 1 (Atgavimo mokestis)": total_plan1_with_battery,
    "Planas 2 (Fiksuotas mokestis)": total_plan2_with_battery,
    "Planas 3 (ESO pasilieka %)":    total_plan3_with_battery,
}
best_plan = min(plans_total, key=plans_total.get)
best_cost = plans_total[best_plan]
worst_cost = max(plans_total.values())

st.success(f"""
🏆 **Geriausias pasirinkimas:** {best_plan}

**Bendra metinė kaina su kaupikliu:** {best_cost:.2f} €/metus

Į šią sumą įeina:
- Namų elektros plano kaina (su kaupikliu)
- EV krovimas darbe: {ev_work_cost:.2f} € ({ev_charge_work_pct:.0f}% EV poreikio darbe)

**Planų palyginimas:**
| Planas | Kaina €/metus |
|--------|--------------|
| Planas 1 (Atgavimo mokestis) | {plans_total['Planas 1 (Atgavimo mokestis)']:.2f} € |
| Planas 2 (Fiksuotas mokestis) | {plans_total['Planas 2 (Fiksuotas mokestis)']:.2f} € |
| Planas 3 (ESO pasilieka %) | {plans_total['Planas 3 (ESO pasilieka %)']:.2f} € |

**Skirtumas tarp geriausio ir blogiausio plano:** {worst_cost - best_cost:.2f} €/metus
""")

st.markdown("---")
st.caption(
    "⚠️ Kadangi naudojami mėnesiniai, o ne valandiniai duomenys, EV ir kaupiklio modelis yra orientacinis. "
    "Planų palyginimui jis yra matematiškai nuoseklus ir praktiškai naudingas. "
    f"Duomenų šaltinis: **{data_mode}** | "
    f"Apskaita: **{accounting_mode}**"
)
