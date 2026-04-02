"""Generate random weather data and questions for the Parallel Weather problem."""

from __future__ import annotations

import random

CITY_POOL = [
    "Tokyo", "Delhi", "Shanghai", "São Paulo", "Mexico City",
    "Cairo", "Mumbai", "Beijing", "Dhaka", "Osaka",
    "New York", "Karachi", "Buenos Aires", "Chongqing", "Istanbul",
    "Kolkata", "Manila", "Lagos", "Rio de Janeiro", "Tianjin",
    "Kinshasa", "Guangzhou", "Los Angeles", "Moscow", "Shenzhen",
    "Lahore", "Bangalore", "Paris", "Bogotá", "Jakarta",
    "Chennai", "Lima", "Bangkok", "Seoul", "Nagoya",
    "Hyderabad", "London", "Tehran", "Chicago", "Chengdu",
    "Nanjing", "Wuhan", "Ho Chi Minh City", "Luanda", "Ahmedabad",
    "Kuala Lumpur", "Xi'an", "Hong Kong", "Dongguan", "Hangzhou",
    "Foshan", "Shenyang", "Riyadh", "Baghdad", "Santiago",
    "Surat", "Madrid", "Suzhou", "Pune", "Harbin",
    "Houston", "Dallas", "Toronto", "Dar es Salaam", "Miami",
    "Belo Horizonte", "Singapore", "Philadelphia", "Atlanta", "Fukuoka",
    "Khartoum", "Barcelona", "Johannesburg", "Saint Petersburg", "Qingdao",
    "Dalian", "Washington", "Yangon", "Alexandria", "Jinan",
    "Guadalajara", "Melbourne", "Sydney", "Taipei", "Chittagong",
    "Kunming", "Changsha", "Nairobi", "Rome", "Berlin",
    "Ankara", "Jaipur", "Lucknow", "Kanpur", "Dubai",
    "Addis Ababa", "Monterrey", "Medellín", "Casablanca", "Kabul",
    "Zhengzhou", "Hefei", "Shantou", "Xiamen", "Nanning",
    "Changchun", "Taiyuan", "Urumqi", "Wenzhou", "Fuzhou",
    "Nanchang", "Guiyang", "Lanzhou", "Wuxi", "Zibo",
    "Tangshan", "Baotou", "Liuzhou", "Yantai", "Huainan",
    "Datong", "Xuzhou", "Handan", "Anshan", "Fushun",
    "Jilin City", "Qiqihar", "Zhuhai", "Haikou", "Hohhot",
    "Xining", "Yinchuan", "Lhasa", "Macau", "Ulaanbaatar",
    "Kathmandu", "Colombo", "Hanoi", "Phnom Penh", "Vientiane",
    "Kuching", "Davao", "Cebu", "Surabaya", "Bandung",
    "Medan", "Semarang", "Palembang", "Makassar", "Mandalay",
    "Chitwan", "Sylhet", "Rajshahi", "Khulna", "Rangpur",
    "Peshawar", "Quetta", "Faisalabad", "Rawalpindi", "Multan",
    "Gujranwala", "Islamabad", "Amritsar", "Varanasi", "Patna",
    "Indore", "Bhopal", "Nagpur", "Visakhapatnam", "Coimbatore",
    "Madurai", "Mysore", "Kochi", "Thiruvananthapuram", "Guwahati",
    "Bhubaneswar", "Ranchi", "Raipur", "Agra", "Meerut",
    "Jodhpur", "Udaipur", "Shimla", "Manali", "Srinagar",
    "Almaty", "Tashkent", "Bishkek", "Dushanbe", "Ashgabat",
    "Tbilisi", "Yerevan", "Baku", "Minsk", "Kyiv",
    "Bucharest", "Warsaw", "Prague", "Budapest", "Vienna",
]

assert len(CITY_POOL) >= 200, f"need >=200 cities, got {len(CITY_POOL)}"


def generate_weather_data(
    num_cities: int = 200,
    seed: int | None = None,
) -> dict[str, dict[str, float]]:
    """Return {city_name: {"temperature": float, "humidity": float}}."""
    rng = random.Random(seed)
    cities = rng.sample(CITY_POOL, min(num_cities, len(CITY_POOL)))
    data: dict[str, dict[str, float]] = {}
    for city in cities:
        temp = round(rng.uniform(-20.0, 40.0), 1)
        humid = round(rng.uniform(0.0, 100.0), 1)
        data[city] = {"temperature": temp, "humidity": humid}
    return data


def generate_questions(
    weather_data: dict[str, dict[str, float]],
    num_questions: int = 5,
    seed: int | None = None,
) -> list[dict]:
    """Pick pairs of cities from weather_data for each question."""
    rng = random.Random(seed)
    city_list = list(weather_data.keys())
    questions: list[dict] = []
    used_pairs: set[tuple[str, str]] = set()

    for q_idx in range(num_questions):
        while True:
            pair = tuple(sorted(rng.sample(city_list, 2)))
            if pair not in used_pairs:
                used_pairs.add(pair)
                break
        city_a, city_b = rng.sample(list(pair), 2)
        questions.append({
            "q_index": q_idx,
            "city_a": city_a,
            "city_b": city_b,
        })
    return questions


def generate_cases(
    num_cases: int = 3,
    num_cities: int = 200,
    num_questions: int = 5,
    seed: int | None = None,
) -> list[dict]:
    """Generate multiple independent test cases."""
    base_rng = random.Random(seed)
    cases: list[dict] = []
    for i in range(num_cases):
        case_seed = base_rng.randint(0, 2**31)
        weather_data = generate_weather_data(num_cities, seed=case_seed)
        questions = generate_questions(
            weather_data,
            num_questions,
            seed=case_seed + 1,
        )
        cases.append({
            "case_index": i,
            "weather_data": weather_data,
            "questions": questions,
        })
    return cases
