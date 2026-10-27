from config import PAGE_SIZE
from timing import track_input


def print_paginated_items(
    title,
    items,
    render_item,
    page_size=None,
    empty_message="No items to show.",
):
    """
    Prints a list with pagination.

    Options after each page:
      N = next page
      A = show all remaining
      C = cancel / stop showing more
    """

    if page_size is None:
        page_size = PAGE_SIZE

    page_size = int(page_size)
    total = len(items)

    print()
    print(title)
    print("=" * 60)
    print(f"Total: {total}")
    print(f"Page size: {page_size}")

    if total == 0:
        print(empty_message)
        return

    if total <= page_size:
        print()
        print(f"Showing 1-{total} of {total}")
        print("-" * 60)

        for display_number, item in enumerate(items, start=1):
            print(render_item(item, display_number))
            print()

        return

    index = 0

    while index < total:
        page = items[index:index + page_size]

        print()
        print(f"Showing {index + 1}-{index + len(page)} of {total}")
        print("-" * 60)

        for offset, item in enumerate(page, start=1):
            display_number = index + offset
            print(render_item(item, display_number))
            print()

        index += len(page)

        if index >= total:
            return

        remaining = total - index

        print(f"{remaining} remaining.")
        print("Options:")
        print(f"  N = show next {page_size}")
        print("  A = show all remaining")
        print("  C = cancel / do not show the rest")

        choice = track_input("Choose option: ").strip().lower()

        if choice == "n":
            continue

        if choice == "a":
            print()
            print(f"Showing remaining {remaining} items")
            print("-" * 60)

            for offset, item in enumerate(items[index:], start=1):
                display_number = index + offset
                print(render_item(item, display_number))
                print()

            return

        if choice == "c":
            print(f"Stopped. {remaining} items not shown.")
            return

        print("Invalid option. Stopping display.")
        return