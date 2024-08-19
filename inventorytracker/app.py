import json
import os
import requests
import sqlite3
from datetime import datetime
import socks
import socket

def get_inventory(start_index, search_key=None, archive_key=None):
    """Gets a single page of inventory from the Hertz Car Sales API.

    Args:
        page_number: The page number to retrieve.
        archive_key: The folder prefix to use for archiving the response.

    Returns:
        A list of dictionaries, where each dictionary represents a car.
    """
    url = f"https://www.hertzcarsales.com/apis/widget/INVENTORY_LISTING_GRID_AUTO_ALL:inventory-data-bus1/getInventory?geoRadius=0&geoZip=78701&sortBy=inventoryDate%20asc&start={start_index}&pageSize=100"

    if search_key:
        url += f"&search={search_key}"

    socks5_proxy = os.environ.get('SOCKS5')
    if socks5_proxy:
        proxy_ip, proxy_port = socks5_proxy.split(':')
        socks.set_default_proxy(socks.SOCKS5, proxy_ip, int(proxy_port))
        socket.socket = socks.socksocket
        response = requests.get(url)
    else:
        response = requests.get(url)

    response.raise_for_status()

    data = response.json()
    inventory = data['inventory']
    tracking_data = data['pageInfo']['trackingData']

    cars = []
    for i, car in enumerate(inventory):
        combined_car = car.copy()
        if i < len(tracking_data):
            combined_car.update(tracking_data[i])
        cars.append(combined_car)

    return cars


def get_cars(vin):
    inventory = get_inventory(0, vin)
    return inventory


def log_changes(uuid, field, old_value, new_value):
    """Logs changes to a file and prints to stdout."""
    message = f"[{datetime.now()}] Change detected for {uuid}: {field} changed from '{old_value}' to '{new_value}'"
    print(message)
    with open('changes.log', 'a') as f:
        f.write(message + '\n')


def store_cars(cars):
    """Stores car data into a SQLite database.

    Args:
        cars: A list of dictionaries, where each dictionary represents a car.
    """

    conn = sqlite3.connect('hertz_inventory.db')
    cursor = conn.cursor()

    # Create tables if they don't exist, updated with new columns
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS cars (
            uuid TEXT PRIMARY KEY,
            vin TEXT,
            price REAL,
            make TEXT,
            model TEXT,
            year INTEGER,
            mileage INTEGER,
            city TEXT,
            state TEXT,
            postal_code TEXT,
            inventory_date TEXT,
            inventory_type TEXT,
            link TEXT,
            first_seen TEXT,
            last_seen TEXT,
            removal_date TEXT
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS car_prices (
            uuid TEXT,
            price REAL,  -- Changed to REAL to handle potential decimal values
            timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (uuid) REFERENCES cars (uuid)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS car_inventory_dates (
            uuid TEXT,
            inventory_date TEXT,
            timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (uuid) REFERENCES cars (uuid)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS car_mileages (
            uuid TEXT,
            mileage INTEGER,
            timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (uuid) REFERENCES cars (uuid)
        )
    ''')

    for car in cars:
        store_car(car, cursor)

    conn.commit()
    conn.close()


def store_car(car, cursor):
    uuid = car['uuid']
    vin = car['vin']
    make = car['make']
    model = car['model']
    year = car['year']
    mileage = int(car['odometer'])
    price = car["internetPrice"]
    city = car['address']['city']
    state = car['address']['state']
    postal_code = car['address']['postalCode']
    inventory_date = car['inventoryDate']
    inventory_type = car['inventoryType']
    link = car['link']

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # Check if the car exists
    cursor.execute("SELECT * FROM cars WHERE uuid=?", (uuid,))
    existing_car = cursor.fetchone()

    if existing_car:
        # Compare values (excluding price) and log changes
        for i, field in enumerate(
            ['uuid', 'vin', 'price', 'make', 'model', 'year', 'mileage',
             'city', 'state', 'postal_code', 'inventory_date',
             'inventory_type', 'link']
        ):
            if field in ['price', 'inventory_date', 'mileage']:
                continue

            if existing_car[i] != locals()[field]:
                log_changes(uuid, field, existing_car[i], locals()[field])

    # Insert or update car data, preserving first_seen
    cursor.execute('''
        INSERT INTO cars (uuid, vin, price, make, model, year, mileage, city, state, postal_code, inventory_date, inventory_type, link, first_seen, last_seen, removal_date)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(uuid) DO UPDATE SET 
            vin = excluded.vin,
            price = excluded.price,
            make = excluded.make,
            model = excluded.model,
            year = excluded.year,
            mileage = excluded.mileage,
            city = excluded.city,
            state = excluded.state,
            postal_code = excluded.postal_code,
            inventory_date = excluded.inventory_date,
            inventory_type = excluded.inventory_type,
            link = excluded.link,
            last_seen = excluded.last_seen,
            removal_date = excluded.removal_date
    ''', (uuid, vin, price, make, model, year, mileage, city, state, postal_code, inventory_date, inventory_type, link, now, now, None))

    # Insert price data into car_prices table
    cursor.execute('''
        INSERT INTO car_prices (uuid, price)
        VALUES (?, ?)
    ''', (uuid, price))

    # Insert inventory_date data into car_inventory_dates table
    cursor.execute('''
        INSERT INTO car_inventory_dates (uuid, inventory_date)
        VALUES (?, ?)
    ''', (uuid, inventory_date))

    # Insert mileage data into car_mileages table
    cursor.execute('''
        INSERT INTO car_mileages (uuid, mileage)
        VALUES (?, ?)
    ''', (uuid, mileage))


def check_and_update_car(uuid, file_prefix):
    """
    Checks if a car is in inventory and updates the database accordingly.

    Args:
        vin: The VIN of the car to check.
    """
    conn = sqlite3.connect('hertz_inventory.db')
    cursor = conn.cursor()

    # Get the car's VIN from the database
    cursor.execute("SELECT vin FROM cars WHERE uuid=?", (uuid,))
    vin = cursor.fetchone()[0]

    potential_cars = get_cars(vin)
    archive_cars(file_prefix, potential_cars, 'by_vin')
    # Get the car from the list with a matching uuid
    car = next((car for car in potential_cars if car['uuid'] == uuid), None)

    if car:
        # Car is in inventory, store/update it
        store_car(car, cursor)
    else:
        # Car is not in inventory, set removal_date
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute('''
            UPDATE cars
            SET removal_date = ?
            WHERE uuid = ?
        ''', (now, uuid))

    conn.commit()
    conn.close()


def archive_cars(file_prefix, cars, name):
    """Appends cars to the JSON archive file."""
    filename = f'{file_prefix}/{name}.txt'
    with open(filename, 'a') as f:  # Open in append mode
        for car in cars:
            json.dump(car, f)
            f.write('\n')  # Separate each car with a newline


def main():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_prefix = f"archive/{timestamp}"
    os.makedirs(file_prefix, exist_ok=True)
    start_index = 0
    encountered_uuids = set()

    while True:
        cars = get_inventory(start_index)
        print(start_index, len(cars))
        if not cars:
            break  # Stop if we get a page with no cars

        for car in cars:
            encountered_uuids.add(car['uuid'])

        archive_cars(file_prefix, cars, "paginated_scan")
        store_cars(cars)
        start_index += 100

    # Get UUIDs from the database that don't have a removal date
    conn = sqlite3.connect('hertz_inventory.db')
    cursor = conn.cursor()
    cursor.execute("SELECT uuid FROM cars WHERE removal_date IS NULL")
    db_uuids = set(row[0] for row in cursor.fetchall())
    conn.close()

    # Calculate potential removed VINs
    potential_removed_uuids = db_uuids - encountered_uuids
    print(f"Potential removed UUIDs: {len(potential_removed_uuids)}. Checking each now..")
    for uuid in potential_removed_uuids:
        print(f"Checking car with UUID {uuid}")
        check_and_update_car(uuid, file_prefix)

if __name__ == "__main__":
    main()
    # print(get_car("5YFEPMAE5NP326733"))
