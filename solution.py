import requests
from bs4 import BeautifulSoup

def print_secret_message(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers)
        print("Status:", r.status_code)
        
        soup = BeautifulSoup(r.text, "html.parser")
        table = soup.find("table")
        print("Table found:", table is not None)
        
        rows = table.find_all("tr")[1:]
        print("Rows found:", len(rows))

        points = []
        for row in rows:
            cells = [c.get_text().strip() for c in row.find_all("td")]
            x, char, y = int(cells[0]), cells[1], int(cells[2])
            points.append((x, y, char))

        max_x = max(x for x, y, _ in points)
        max_y = max(y for _, y, _ in points)
        grid = [[" "] * (max_x + 1) for _ in range(max_y + 1)]

        for x, y, char in points:
            grid[y][x] = char

        print("\n".join("".join(row) for row in grid))

    except Exception as e:
        print("ERROR:", e)

print_secret_message(
    "https://docs.google.com/document/d/e/"
    "2PACX-1vSvM5gDlNvt7npYHhp_XfsJvuntUhq184By5xO_pA4b_"
    "gCWeXb6dM6ZxwN8rE6S4ghUsCj2VKR21oEP/pub"
)