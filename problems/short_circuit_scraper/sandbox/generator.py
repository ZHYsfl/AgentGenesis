"""Generate random user-profile test cases for The Short-Circuit Scraper."""

from __future__ import annotations

import random
import string
from typing import Optional

FIRST_NAMES = [
    "Alice", "Bob", "Charlie", "Diana", "Edward", "Fiona", "George",
    "Hannah", "Ivan", "Julia", "Kevin", "Laura", "Michael", "Nina",
    "Oscar", "Penny", "Quentin", "Rachel", "Samuel", "Tina",
    "Uma", "Victor", "Wendy", "Xavier", "Yuki", "Zane",
]

LAST_NAMES = [
    "Johnson", "Smith", "Williams", "Brown", "Davis", "Martinez",
    "Anderson", "Thomas", "Jackson", "White", "Harris", "Clark",
    "Lewis", "Robinson", "Walker", "Young", "Allen", "King",
    "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores",
]

EMAIL_DOMAINS = [
    "gmail.com", "outlook.com", "yahoo.com", "protonmail.com",
    "fastmail.com", "icloud.com", "hotmail.com", "zoho.com",
    "mail.com", "aol.com", "tutanota.com", "hey.com",
]

LOCATIONS = [
    "New York, NY", "San Francisco, CA", "Austin, TX", "Chicago, IL",
    "Seattle, WA", "Denver, CO", "Boston, MA", "Portland, OR",
    "Miami, FL", "Nashville, TN", "Atlanta, GA", "Los Angeles, CA",
    "Toronto, ON", "London, UK", "Berlin, DE", "Tokyo, JP",
    "Sydney, AU", "Paris, FR", "Amsterdam, NL", "Singapore, SG",
]

PLAN_TIERS = [
    "Free", "Basic", "Standard", "Premium", "Enterprise",
    "Gold", "Silver", "Platinum", "Pro", "Starter",
]

MEMBER_ID_PREFIXES = [
    "MEM", "USR", "ACC", "PRF", "CUS", "SUB", "REG", "VIP",
]

JOIN_PHRASES = [
    "signed up on {date}",
    "joined the platform on {date}",
    "has been a member since {date}",
    "registered back on {date}",
    "first appeared in our system on {date}",
    "created their account on {date}",
    "became a user on {date}",
    "onboarded on {date}",
]


def _random_email(first: str, last: str, rng: random.Random) -> str:
    sep = rng.choice([".", "_", ""])
    domain = rng.choice(EMAIL_DOMAINS)
    num_suffix = rng.choice(["", str(rng.randint(1, 999))])
    return f"{first.lower()}{sep}{last.lower()}{num_suffix}@{domain}"


def _random_member_id(rng: random.Random) -> str:
    prefix = rng.choice(MEMBER_ID_PREFIXES)
    digits = "".join(rng.choices(string.digits, k=rng.randint(4, 7)))
    sep = rng.choice(["-", "_", ""])
    suffix_letters = "".join(rng.choices(string.ascii_uppercase, k=rng.randint(0, 2)))
    return f"{prefix}{sep}{digits}{suffix_letters}"


def _random_date_str(rng: random.Random) -> str:
    year = rng.randint(2018, 2025)
    month = rng.randint(1, 12)
    day = rng.randint(1, 28)
    fmt = rng.choice([
        f"{year}-{month:02d}-{day:02d}",
        f"{month:02d}/{day:02d}/{year}",
        f"{_month_name(month)} {day}, {year}",
        f"{day} {_month_name(month)} {year}",
    ])
    return fmt


def _month_name(m: int) -> str:
    names = [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ]
    return names[m - 1]


PROFILE_TEMPLATES = [
    (
        "So this is {name}'s page! They {join_phrase}. "
        "You can reach them at {email} if you need anything — though they "
        "prefer in-app messages. Their account is registered under membership "
        "number {member_id}. Based out of {location}, currently on our "
        "{plan} tier."
    ),
    (
        "Profile for {name}. Location: somewhere around {location}. "
        "This user {join_phrase} and has been pretty active ever since. "
        "For urgent matters, their contact email is {email}. "
        "If you need to look them up internally, their member ID is {member_id}. "
        "They're on the {plan} plan."
    ),
    (
        "Hey, just pulled up the records for {name}. They're based in "
        "{location} and {join_phrase}. Email on file: {email}. "
        "Membership reference: {member_id}. Subscription level: {plan}. "
        "That's everything we have."
    ),
    (
        "User report — {name}\n"
        "We've got them tagged under the {plan} subscription. They "
        "{join_phrase}. Geographically, they seem to be around {location}. "
        "The email address listed is {email} and their unique member "
        "identifier reads {member_id}."
    ),
    (
        "Alright, here's what the scraper picked up on {name}. The profile "
        "page says they're a {plan} member who {join_phrase}. "
        "Contact info includes the email {email}. "
        "Their member number on record is {member_id}. "
        "Last known location: {location}."
    ),
    (
        "Data dump for {name}: currently residing in {location}, "
        "subscribed at the {plan} level. According to the records they "
        "{join_phrase}. To reach out, use {email}. "
        "Internal reference code: {member_id}. Nothing else flagged."
    ),
    (
        "{name} — {plan} tier user from {location}. "
        "They {join_phrase}. The email that's associated with this account "
        "is {email}; their system-assigned membership ID is {member_id}. "
        "Profile looks clean, no anomalies."
    ),
    (
        "Okay so {name} is on the {plan} plan. They {join_phrase}. "
        "If you wanna email them it's {email}. "
        "Their member code thing is {member_id}. "
        "I think they're from {location} area or something like that."
    ),
    (
        "=== {name} ===\n"
        "Plan: {plan} | Region: {location}\n"
        "This member {join_phrase}. Preferred contact channel: email at "
        "{email}. For internal tracking purposes, the membership "
        "identifier is {member_id}."
    ),
    (
        "Just checked the database for {name}. Looks like they "
        "{join_phrase} and are located in {location}. "
        "They're paying for the {plan} subscription. "
        "Their email — {email} — is the only contact we have. "
        "Oh, and the member ID is {member_id} if you need that."
    ),
    (
        "Scraper results for user '{name}':\n"
        "The person appears to be in the {location} area. They "
        "{join_phrase}. Email address found on their public profile: "
        "{email}. The membership badge shows {member_id}. "
        "Current subscription: {plan}."
    ),
    (
        "Found {name}'s info! Quick summary: {plan} member, based in "
        "{location}. They {join_phrase}. Contact email is "
        "{email}. Their member registration number is {member_id}. "
        "That's the gist of it."
    ),
]

ERROR_TEMPLATES = [
    "Error: endpoint {i} returned no data for user '{user_name}'. "
    "The server responded with: 404 Not Found — user profile not available at this location.",

    "Error: scraper agent dispatched to endpoint {i} could not locate any records "
    "for '{user_name}'. Endpoint returned empty results after full crawl.",

    "Error: no matching profile found at endpoint {i} for user '{user_name}'. "
    "The search timed out with zero relevant hits.",

    "Error: endpoint {i} has no data for '{user_name}'. "
    "The crawler exhausted all pages without finding a matching user profile.",

    "Error: request to endpoint {i} for user '{user_name}' returned 404. "
    "This endpoint does not appear to host the target profile.",
]


def generate_cases(
    num_cases: int = 5,
    num_endpoints: int = 10,
    seed: int | None = None,
) -> list[dict]:
    rng = random.Random(seed)
    cases: list[dict] = []

    for i in range(num_cases):
        first = rng.choice(FIRST_NAMES)
        last = rng.choice(LAST_NAMES)
        user_name = f"{first} {last}"

        email = _random_email(first, last, rng)
        member_id = _random_member_id(rng)
        location = rng.choice(LOCATIONS)
        plan = rng.choice(PLAN_TIERS)
        date_str = _random_date_str(rng)
        join_phrase = rng.choice(JOIN_PHRASES).format(date=date_str)
        valid_index = rng.randint(0, num_endpoints - 1)

        template = rng.choice(PROFILE_TEMPLATES)
        profile_data = template.format(
            name=user_name,
            email=email,
            member_id=member_id,
            location=location,
            plan=plan,
            join_phrase=join_phrase,
        )

        error_template = rng.choice(ERROR_TEMPLATES)

        cases.append({
            "case_index": i,
            "user_name": user_name,
            "valid_index": valid_index,
            "profile_data": profile_data,
            "expected_email": email,
            "expected_member_id": member_id,
            "num_endpoints": num_endpoints,
            "error_template": error_template,
        })

    return cases
