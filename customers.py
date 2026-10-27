from difflib import get_close_matches

from sqlalchemy import text

from parsing import parse_invoice_filename
from timing import track_input


def normalize_customer_name(name):
    if not name:
        return None

    return " ".join(str(name).strip().split())


def get_existing_customers(engine):
    with engine.begin() as conn:
        rows = conn.execute(text("select name from customers order by name")).fetchall()

    return [row[0] for row in rows]


def create_customer(engine, customer_name):
    with engine.begin() as conn:
        conn.execute(
            text("""
                insert into customers (name)
                values (:name)
                on conflict (name) do nothing
            """),
            {"name": customer_name},
        )


def confirm_customer_match(engine, parsed_customer):
    parsed_customer = normalize_customer_name(parsed_customer)
    existing_customers = get_existing_customers(engine)

    exact_matches = [
        customer
        for customer in existing_customers
        if customer.lower() == parsed_customer.lower()
    ]

    if exact_matches:
        return exact_matches[0]

    close_matches = get_close_matches(
        parsed_customer,
        existing_customers,
        n=5,
        cutoff=0.6,
    )

    print("\nCustomer name not found in database.")
    print(f"Parsed from filename: {parsed_customer}")

    if close_matches:
        print("\nClose matches:")
        for i, match in enumerate(close_matches, start=1):
            print(f"{i}. {match}")
    else:
        print("\nNo close matches found.")

    print("\nOptions:")
    print("Enter a number to use a close match")
    print("Enter C to create new customer")
    print("Enter Q to fail this file")

    while True:
        choice = track_input("Choose option: ").strip()

        if choice.lower() == "q":
            raise ValueError(f"Customer not confirmed: {parsed_customer}")

        if choice.lower() == "c":
            create_customer(engine, parsed_customer)
            return parsed_customer

        if choice.isdigit():
            index = int(choice) - 1

            if 0 <= index < len(close_matches):
                return close_matches[index]

        print("Invalid choice. Try again.")


def get_confirmed_customer_for_file(engine, file_path):
    filename_data = parse_invoice_filename(file_path.name)

    return confirm_customer_match(
        engine=engine,
        parsed_customer=filename_data["customer"],
    )