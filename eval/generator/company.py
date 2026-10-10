"""Synthetic company identities: names, STIRs, regions, banks, accounts. All fictional."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

PLACES = [
    "Toshkent", "Samarqand", "Buxoro", "Farg'ona", "Andijon", "Namangan", "Qarshi", "Termiz",
    "Jizzax", "Navoiy", "Urganch", "Nukus", "Guliston", "Chirchiq", "Olmaliq", "Qo'qon",
    "Marg'ilon", "Shahrisabz", "Angren", "Denov", "Xiva", "Kattaqo'rg'on", "Bekobod", "Chust",
]
NICE = [
    "Farovon", "Navro'z", "Oltin Vodiy", "Nurafshon", "Ishonch", "Barakali", "Yangi Hayot",
    "Bunyodkor", "Mehnat", "Kamalak", "Sharq", "Ziyo", "Omad", "Durdona", "Gulshan", "Bahor",
    "Zafar", "Saodat", "Oqtosh", "Oydin", "Yulduz", "Sarbon", "Tong", "Shodlik", "Ilhom",
    "Bog'ishamol", "Zarafshon", "Afrosiyob", "Lazzat", "Nihol",
]
# industry -> (product words, display industry, cogs share range, opex share range)
INDUSTRIES = {
    "textile": (["Tekstil", "Mato", "Tikuv", "Ip-Kalava"], "Textile manufacturing", (0.58, 0.72), (0.12, 0.20)),
    "furniture": (["Mebel", "Yog'och"], "Furniture manufacturing", (0.55, 0.68), (0.14, 0.22)),
    "bakery": (["Non", "Un Mahsulotlari"], "Bakery", (0.60, 0.72), (0.12, 0.20)),
    "dairy": (["Sut", "Sut Mahsulotlari"], "Dairy", (0.66, 0.78), (0.10, 0.16)),
    "food_dist": (["Savdo", "Oziq-ovqat Savdo"], "Food distribution", (0.82, 0.90), (0.04, 0.08)),
    "construction": (["Qurilish", "Qurilish Materiallari"], "Construction", (0.70, 0.82), (0.07, 0.12)),
    "plastics": (["Plastik", "Polimer"], "Plastics manufacturing", (0.62, 0.74), (0.10, 0.16)),
    "metal": (["Metall Servis", "Metall"], "Metalworking", (0.64, 0.76), (0.10, 0.15)),
    "agro": (["Agro Servis", "Agro"], "Agricultural services", (0.60, 0.75), (0.10, 0.16)),
    "fruit_export": (["Meva Eksport", "Meva-Sabzavot"], "Fruit export", (0.70, 0.82), (0.06, 0.10)),
    "auto_parts": (["Avto Ehtiyot", "Avto Savdo"], "Auto parts retail", (0.74, 0.84), (0.08, 0.12)),
    "transport": (["Logistik", "Trans Servis"], "Freight transport", (0.62, 0.74), (0.10, 0.16)),
    "pharma": (["Farm Savdo", "Dori-Darmon"], "Pharmacy retail", (0.72, 0.82), (0.08, 0.13)),
    "oil": (["Yog' Zavodi", "Moy"], "Oil processing", (0.74, 0.85), (0.05, 0.09)),
    "printing": (["Poligraf", "Qog'oz"], "Printing", (0.58, 0.70), (0.12, 0.18)),
    "tourism": (["Tur Servis", "Mehmonxona"], "Tourism services", (0.50, 0.65), (0.16, 0.25)),
}
REGIONS = [
    "Tashkent", "Tashkent region", "Samarqand", "Buxoro", "Farg'ona", "Andijon", "Namangan",
    "Qashqadaryo", "Surxondaryo", "Jizzax", "Navoiy", "Xorazm", "Qoraqalpog'iston", "Sirdaryo",
]
FORMS = ["MChJ", "MChJ", "MChJ", "MChJ", "XK", "AJ"]
# fictional banks (name, MFO)
BANKS = [
    ("Navbahor Bank ATB", "01121"), ("Oqsaroy Bank ATB", "01153"), ("Zarafshon Kredit Bank", "00987"),
    ("Bodomzor Bank ATB", "01204"), ("Yangi Asr Bank", "01089"), ("Sarbon Moliya Bank", "00962"),
]
LENDERS = [
    "Oltin Qadam mikromoliya tashkiloti MChJ", "Tez Kredit mikromoliya tashkiloti MChJ",
    "Ishonchli Lombard MChJ", "Barqaror Moliya MChJ",
]
SURNAMES = ["Abdullayev", "Karimov", "Rahimov", "Yusupov", "Toshmatov", "Ergashev", "Nazarov",
            "Qodirov", "Sobirov", "Mirzayev", "Xolmatov", "Ismoilov", "Saidov", "Jo'rayev"]
GIVEN = ["A.", "B.", "D.", "F.", "G.", "J.", "K.", "L.", "M.", "N.", "O.", "R.", "S.", "Sh.", "U.", "Z."]


@dataclass
class Company:
    name: str
    stir: str
    industry_key: str
    industry: str
    region: str
    bank: str
    mfo: str
    account: str
    director: str
    accountant: str
    employees: int
    since: int
    address: str = ""
    extra: dict = field(default_factory=dict)


def stir(rng: np.random.Generator) -> str:
    return str(int(rng.integers(2, 4))) + "".join(str(int(d)) for d in rng.integers(0, 10, 8))


def account(rng: np.random.Generator, balance: str = "20208") -> str:
    # 5 balance-account digits, 3 currency (000 = UZS), 1 key, 8 client code, 3 sequence
    return balance + "000" + str(int(rng.integers(0, 10))) + "".join(
        str(int(d)) for d in rng.integers(0, 10, 8)) + "001"


def person(rng: np.random.Generator) -> str:
    return f"{rng.choice(SURNAMES)} {rng.choice(GIVEN)}"


def company_name(rng: np.random.Generator, industry_key: str) -> str:
    products = INDUSTRIES[industry_key][0]
    first = rng.choice(NICE + PLACES)
    return f"{first} {rng.choice(products)} {rng.choice(FORMS)}"


def make_company(rng: np.random.Generator, industry_key: str | None = None, **over) -> Company:
    key = industry_key or str(rng.choice(list(INDUSTRIES)))
    bank, mfo = BANKS[int(rng.integers(0, len(BANKS)))]
    region = str(rng.choice(REGIONS))
    c = Company(
        name=company_name(rng, key), stir=stir(rng), industry_key=key, industry=INDUSTRIES[key][1],
        region=region, bank=bank, mfo=mfo, account=account(rng), director=person(rng),
        accountant=person(rng), employees=int(rng.integers(8, 120)), since=int(rng.integers(2008, 2022)),
        address=f"{region}, {rng.choice(['Mustaqillik', 'Amir Temur', 'Navoiy', 'Bobur', 'Islom Karimov', 'Mirzo Ulug\'bek'])} ko'chasi, {int(rng.integers(1, 180))}-uy",
    )
    for k, v in over.items():
        setattr(c, k, v)
    return c


def counterparty(rng: np.random.Generator, industry_key: str | None = None) -> tuple[str, str]:
    key = industry_key or str(rng.choice(list(INDUSTRIES)))
    return company_name(rng, key), stir(rng)
