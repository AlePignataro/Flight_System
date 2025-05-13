DROP TABLE IF EXISTS Work_For;
DROP TABLE IF EXISTS Ticket;
DROP TABLE IF EXISTS Customer;
DROP TABLE IF EXISTS Booking_Agent;
DROP TABLE IF EXISTS Airline_Staff;
DROP TABLE IF EXISTS Flight;
DROP TABLE IF EXISTS Airplane;
DROP TABLE IF EXISTS Airport;
DROP TABLE IF EXISTS Airline;

CREATE TABLE Airline (
    Name VARCHAR(100) PRIMARY KEY
);

CREATE TABLE Airport (
    Name CHAR(20) PRIMARY KEY,
    City VARCHAR(100) NOT NULL
);

CREATE TABLE Airplane (
    Airline VARCHAR(100),
    Airplane_ID CHAR(15) PRIMARY KEY,
    Number_Seats INT NOT NULL,
    FOREIGN KEY (Airline) REFERENCES Airline(Name)
);

CREATE TABLE Flight (
    Flight_ID CHAR(20) PRIMARY KEY,
    Airline VARCHAR(100),
    Airplane_ID CHAR(15),
    Departure_Airport CHAR(20),
    Departure_Date DATE,
    Departure_Time TIME,
    Arrival_Airport CHAR(20),
    Arrival_Date DATE,
    Arrival_Time TIME,
    Status_ CHAR(30),
    Price DECIMAL(6, 2),
    FOREIGN KEY (Airline) REFERENCES Airline(Name),
    FOREIGN KEY (Airplane_ID) REFERENCES Airplane(Airplane_ID),
    FOREIGN KEY (Departure_Airport) REFERENCES Airport(Name),
    FOREIGN KEY (Arrival_Airport) REFERENCES Airport(Name)
);

CREATE TABLE Airline_Staff (
    Username VARCHAR(50) PRIMARY KEY,
    Airline VARCHAR(100),
    First_Name VARCHAR(100),
    Middle_Name VARCHAR(100),
    Last_Name VARCHAR(100),
    Password VARCHAR(255),
    DoB DATE,
    Role VARCHAR(50),
    FOREIGN KEY (Airline) REFERENCES Airline(Name)
);

CREATE TABLE Booking_Agent (
    Booking_Agent_ID CHAR(10) PRIMARY KEY,
    Email VARCHAR(254) UNIQUE,
    Password VARCHAR(255)
);

CREATE TABLE Work_For (
    Airline VARCHAR(100),
    Booking_Agent_ID CHAR(10),
    PRIMARY KEY (Airline, Booking_Agent_ID),
    FOREIGN KEY (Booking_Agent_ID) REFERENCES Booking_Agent(Booking_Agent_ID),
    FOREIGN KEY (Airline) REFERENCES Airline(Name)
);

CREATE TABLE Customer (
    Email CHAR(254) PRIMARY KEY,
    First_Name VARCHAR(100),
    Middle_Name VARCHAR(100),
    Last_Name VARCHAR(100),
    Password VARCHAR(255),
    State VARCHAR(60),
    City VARCHAR(100),
    Zip_Code CHAR(10),
    Building_Name VARCHAR(100),
    Phone_Number VARCHAR(15),
    Passport_Number CHAR(15),
    Passport_Country CHAR(60),
    Passport_Expiration_Date DATE,
    DoB DATE
);

CREATE TABLE Ticket (
    Ticket_ID        CHAR(20)  PRIMARY KEY,
    Airline          VARCHAR(100),
    Flight_ID        CHAR(20),
    Customer_Email   CHAR(254),          -- ← same type/length as Customer.Email
    Booking_Agent_ID CHAR(10),
    Purchase_Date    DATE,
    FOREIGN KEY (Airline)          REFERENCES Airline(Name),
    FOREIGN KEY (Flight_ID)        REFERENCES Flight(Flight_ID),
    FOREIGN KEY (Customer_Email)   REFERENCES Customer(Email),   -- typo fixed
    FOREIGN KEY (Booking_Agent_ID) REFERENCES Booking_Agent(Booking_Agent_ID)
);



-- Airlines
INSERT INTO Airline (Name) VALUES
('United Airlines'), ('Lufthansa'), ('Emirates'),
('Qatar Airways'), ('British Airways');

-- Airports
INSERT INTO Airport (Name, City) VALUES
('SFO','San Francisco'), ('DFW','Dallas'), ('DXB','Dubai'),
('LHR','London'), ('JFK','New York'), ('ORD','Chicago'),
('LAX','Los Angeles'), ('DOH','Doha');

-- Airplanes
INSERT INTO Airplane (Airplane_ID, Airline, Number_Seats) VALUES
('N123UA','United Airlines',280),
('D-ABCD','Lufthansa',300),
('A6-EQA','Emirates',350),
('A7-BBC','Qatar Airways',320),
('G-BAWB','British Airways',290);

-- Customers (note table renamed)
INSERT INTO Customer
  (Email, First_Name, Middle_Name, Last_Name, Password,
   State, City, Zip_Code, Building_Name, Phone_Number,
   Passport_Number, Passport_Country, Passport_Expiration_Date, DoB)
VALUES
('karen@gmail.com',  'Karen',    'Maria',  'Roberts',   'karensecure', 'NY','New York',      '10003','Building L','4445556667','K5566778','USA','2030-05-11','1993-07-21'),
('leo@gmail.com',    'Leo',      'Tomas',  'Gomez',     'leopass',     'CA','San Francisco', '94101','Building M','5556667778','L1122334','USA','2029-11-30','1992-10-15'),
('maria@gmail.com',  'Maria',     NULL,    'Fernandez', 'maria123',    'TX','Dallas',        '75001','Building N','6667778889','M4455667','USA','2031-06-19','1989-05-14'),
('nathan@gmail.com', 'Nathan',   'Jhon',   'Parker',    'nathanpass',  'IL','Chicago',       '60605','Building O','7778889990','N7788990','USA','2028-12-01','1994-08-23'),
('oliver@gmail.com', 'Oliver',     NULL,   'Brown',     'oliverpwd',   'CA','San Francisco', '94101','Building P','8889990001','O9900112','USA','2030-02-10','1991-12-02'),
('olivia@gmail.com', 'Olivia',     NULL,   'Nelson',    'oliviapwd',   'FL','Miami',         '33109','Building P','8889990002','O9900113','USA','2030-02-10','1991-12-02'),
('paul@gmail.com',   'Paul',     'Henry',  'Carter',    'paulpass',    'WA','Seattle',       '98101','Building Q','9991112223','P1234567','USA','2029-07-19','1990-03-11'),
('emma@gmail.com',   'Emma',     'Grace',  'Smith',     'emmapwd',     'MA','Boston',        '02108','Building R','9992223334','E2345678','USA','2031-03-22','1992-09-05'),
('liam@gmail.com',   'Liam',       NULL,   'Johnson',   'liampass',    'AZ','Phoenix',       '85001','Building S','9993334445','L3456789','USA','2028-10-30','1993-11-29'),
('noah@gmail.com',   'Noah',     'Michael','Williams',  'noahpwd',     'CO','Denver',        '80202','Building T','9994445556','N4567890','USA','2029-05-15','1994-02-17'),
('ava@gmail.com',    'Ava',        NULL,   'Jones',     'avapass',     'NV','Las Vegas',     '89109','Building U','9995556667','A5678901','USA','2030-12-12','1989-06-09'),
('isabella@gmail.com','Isabella','Rose',   'Garcia',    'isabpwd',     'GA','Atlanta',       '30301','Building V','9996667778','I6789012','USA','2031-01-25','1991-08-24'),
('sophia@gmail.com', 'Sophia',   'Anne',   'Martinez',  'sophiapwd',   'NC','Charlotte',     '28202','Building W','9997778889','S7890123','USA','2029-09-09','1990-12-18'),
('jacob@gmail.com',  'Jacob',    'Lee',    'Rodriguez', 'jacobpass',   'OH','Columbus',      '43085','Building X','9998889990','J8901234','USA','2030-04-04','1992-04-16'),
('mia@gmail.com',    'Mia',        NULL,   'Hernandez', 'miapwd',      'PA','Philadelphia',  '19103','Building Y','9990001112','M9012345','USA','2028-08-08','1993-10-10'),
('ethan@gmail.com',  'Ethan',    'David',  'Lopez',     'ethanpass',   'TX','Houston',       '77002','Building Z','9991112224','E0123456','USA','2031-06-01','1991-05-02'),
('amelia@gmail.com', 'Amelia',   'Jane',   'Gonzalez',  'ameliapwd',   'WA','Seattle',       '98104','Building AA','9992223335','AM123456','USA','2030-11-20','1990-01-15'),
('lucas@gmail.com',  'Lucas',    'Ryan',   'Wilson',    'lucaspass',   'IL','Springfield',   '62701','Building BB','9993334446','LU234567','USA','2029-02-28','1994-07-07'),
('harper@gmail.com', 'Harper',   'Kate',   'Anderson',  'harperpwd',   'CA','Los Angeles',   '90012','Building CC','9994445557','H345678','USA','2031-10-15','1992-03-03'),
('logan@gmail.com',  'Logan',      NULL,   'Thomas',    'loganpass',   'FL','Orlando',       '32801','Building DD','9995556668','LO456789','USA','2029-12-31','1988-11-11');

-- Booking agents
INSERT INTO Booking_Agent (Booking_Agent_ID, Email, Password) VALUES
('BA10002','agent2@travel.com','securepass2'), 
('BA10003','agent1@travel.com','securepass12'),
('BA10004','agent4@travel.com','securepass4'),
('BA10005','agent5@travel.com','securepass5'),
('BA10006','agent6@travel.com','securepass6'),
('BA10007','agent7@travel.com','securepass7'),
('BA10008','agent8@travel.com','securepass8'),
('BA10009','agent9@travel.com', 'securepass9'),
('BA10010','agent10@travel.com','securepass10'),
('BA10011','agent11@travel.com','securepass11'),
('BA10012','agent12@travel.com','securepass12a'),
('BA10013','agent13@travel.com','securepass13'),
('BA10014','agent14@travel.com','securepass14'),
('BA10015','agent15@travel.com','securepass15'),
('BA10016','agent16@travel.com', 'securepass16'),
('BA10017','agent17@travel.com','securepass17'),
('BA10018','agent18@travel.com','securepass18'),
('BA10019','agent19@travel.com','securepass19'),
('BA10020','agent20@travel.com','securepass20'),
('BA10021','agent21@travel.com','securepass21');

/* ─────────────────── 20 Work_For links ───────────────────
   4 agents per airline so every carrier is evenly covered  */
INSERT INTO Work_For (Airline, Booking_Agent_ID) VALUES
-- United Airlines
('United Airlines','BA10002'),
('United Airlines','BA10007'),
('United Airlines','BA10012'),
('United Airlines','BA10017'),

-- Lufthansa
('Lufthansa','BA10003'),
('Lufthansa','BA10008'),
('Lufthansa','BA10013'),
('Lufthansa','BA10018'),

-- Emirates
('Emirates','BA10004'),
('Emirates','BA10009'),
('Emirates','BA10014'),
('Emirates','BA10019'),

-- Qatar Airways
('Qatar Airways','BA10005'),
('Qatar Airways','BA10010'),
('Qatar Airways','BA10015'),
('Qatar Airways','BA10020'),

-- British Airways
('British Airways','BA10006'),
('British Airways','BA10011'),
('British Airways','BA10016'),
('British Airways','BA10021');

-- Airline staff
INSERT INTO Airline_Staff (Username, Airline, First_Name, Middle_Name, Last_Name,
                           Password, DoB, Role)
VALUES
('ua_admin',     'United Airlines', 'Alice',  'Marie',  'Johnson',  'passUA1', '1987-01-02', 'Admin'),
('ua_operator',  'United Airlines', 'Brian',  'Lee',    'Adams',    'passUA2', '1988-02-03', 'Operator'),
('ua_both',      'United Airlines', 'Cynthia','Rose',   'Parker',   'passUA3', '1989-03-04', 'Admin & Operator'),
('ua_none',      'United Airlines', 'Daniel', 'James',  'Young',    'passUA4', '1990-04-05', NULL),
('lh_admin',     'Lufthansa',       'Eva',    'Lotte',  'Schneider','passLH1', '1987-05-06', 'Admin'),
('lh_operator',  'Lufthansa',       'Felix',  'Karl',   'Meyer',    'passLH2', '1988-06-07', 'Operator'),
('lh_both',      'Lufthansa',       'Greta',  'Ute',    'Fischer',  'passLH3', '1989-07-08', 'Admin & Operator'),
('lh_none',      'Lufthansa',       'Hans',   'Otto',   'Becker',   'passLH4', '1990-08-09', NULL),
('ek_admin',     'Emirates',        'Ibrahim','Ahmad',  'Khan',     'passEK1', '1987-09-10', 'Admin'),
('ek_operator',  'Emirates',        'Jamil',  'Said',   'Haddad',   'passEK2', '1988-10-11', 'Operator'),
('ek_both',      'Emirates',        'Karim',  'Yusuf',  'Ali',      'passEK3', '1989-11-12', 'Admin & Operator'),
('ek_none',      'Emirates',        'Layla',  'Aisha',  'Rahman',   'passEK4', '1990-12-13', NULL),
('qr_admin',     'Qatar Airways',   'Mahmoud','Hassan', 'Qadir',    'passQR1', '1987-02-14', 'Admin'),
('qr_operator',  'Qatar Airways',   'Nadia',  'Fatima', 'Salim',    'passQR2', '1988-03-15', 'Operator'),
('qr_both',      'Qatar Airways',   'Omar',   'Abdul',  'Karim',    'passQR3', '1989-04-16', 'Admin & Operator'),
('qr_none',      'Qatar Airways',   'Parvin', 'Zara',   'Latif',    'passQR4', '1990-05-17', NULL),
('ba_admin',     'British Airways', 'Quentin','George', 'Watson',   'passBA1', '1987-06-18', 'Admin'),
('ba_operator',  'British Airways', 'Rachel', 'Anne',   'Campbell', 'passBA2', '1988-07-19', 'Operator'),
('ba_both',      'British Airways', 'Samuel', 'Peter',  'Clark',    'passBA3', '1989-08-20', 'Admin & Operator'),
('ba_none',      'British Airways', 'Tara',   'Helen',  'Bennett',  'passBA4', '1990-09-21', NULL);


-- Flights (dates kept in future)
INSERT INTO Flight (Flight_ID, Airline, Airplane_ID, Departure_Airport,
                    Departure_Date, Departure_Time, Arrival_Airport,
                    Arrival_Date, Arrival_Time, Status_, Price)
VALUES
('UA501','United Airlines','N123UA','JFK','2025-04-01','07:00:00','SFO','2025-04-01','12:00:00','Upcoming', 450.00),
('UA502','United Airlines','N123UA','SFO','2025-04-10','14:30:00','ORD','2025-04-10','20:00:00','Delayed',  460.00),
('UA503','United Airlines','N123UA','ORD','2025-04-15','08:15:00','DFW','2025-04-15','11:10:00','Departed', 350.00),
('UA504','United Airlines','N123UA','DFW','2025-04-20','09:45:00','JFK','2025-04-20','14:35:00','Arrived',  400.00),
('UA505','United Airlines','N123UA','LAX','2025-04-25','06:00:00','JFK','2025-04-25','14:25:00','Cancelled',480.00),
('LH601','Lufthansa','D-ABCD','LHR','2025-04-02','09:00:00','ORD','2025-04-02','14:00:00','Upcoming', 600.00),
('LH602','Lufthansa','D-ABCD','ORD','2025-04-08','16:00:00','LHR','2025-04-09','05:45:00','Delayed',  620.00),
('LH603','Lufthansa','D-ABCD','LHR','2025-04-12','07:30:00','JFK','2025-04-12','10:00:00','Departed', 580.00),
('LH604','Lufthansa','D-ABCD','JFK','2025-04-18','12:15:00','LHR','2025-04-18','23:50:00','Arrived',  595.00),
('LH605','Lufthansa','D-ABCD','LHR','2025-04-24','11:10:00','SFO','2025-04-24','19:40:00','Cancelled',640.00),
('EK701','Emirates','A6-EQA','DXB','2025-04-03','20:00:00','JFK','2025-04-04','08:30:00','Upcoming', 1200.00),
('EK702','Emirates','A6-EQA','DXB','2025-04-09','02:00:00','LAX','2025-04-09','12:40:00','Delayed',  1250.00),
('EK703','Emirates','A6-EQA','JFK','2025-04-13','10:30:00','DXB','2025-04-14','07:15:00','Departed', 1180.00),
('EK704','Emirates','A6-EQA','DXB','2025-04-19','18:20:00','LHR','2025-04-20','00:10:00','Arrived',  1225.00),
('EK705','Emirates','A6-EQA','DXB','2025-04-26','21:10:00','SFO','2025-04-27','08:55:00','Cancelled',1300.00),
('QR801','Qatar Airways','A7-BBC','DOH','2025-04-04','10:00:00','LAX','2025-04-04','20:00:00','Upcoming', 1300.00),
('QR802','Qatar Airways','A7-BBC','DOH','2025-04-07','08:20:00','JFK','2025-04-07','15:30:00','Delayed',  1280.00),
('QR803','Qatar Airways','A7-BBC','LAX','2025-04-11','22:55:00','DOH','2025-04-12','08:30:00','Departed', 1350.00),
('QR804','Qatar Airways','A7-BBC','DOH','2025-04-17','13:15:00','ORD','2025-04-17','21:10:00','Arrived',  1260.00),
('QR805','Qatar Airways','A7-BBC','DOH','2025-04-23','09:45:00','SFO','2025-04-23','19:50:00','Cancelled',1315.00),
('BA901','British Airways','G-BAWB','LHR','2025-04-05','09:00:00','SFO','2025-04-05','18:00:00','Upcoming', 750.00),
('BA902','British Airways','G-BAWB','LHR','2025-04-06','14:50:00','JFK','2025-04-06','17:40:00','Delayed',  730.00),
('BA903','British Airways','G-BAWB','JFK','2025-04-14','18:30:00','LHR','2025-04-15','06:30:00','Departed', 760.00),
('BA904','British Airways','G-BAWB','LHR','2025-04-21','07:25:00','ORD','2025-04-21','10:25:00','Arrived',  790.00),
('BA905','British Airways','G-BAWB','LHR','2025-04-28','11:15:00','LAX','2025-04-28','14:35:00','Cancelled',780.00);


-- Tickets
INSERT INTO Ticket (Ticket_ID, Airline, Flight_ID, Customer_Email, Booking_Agent_ID, Purchase_Date)
VALUES
/* ───── United Airlines (4 new + 1 extra) ───── */
('TKT1013','United Airlines','UA502','olivia@gmail.com','BA10002','2025-03-01'),
('TKT1014','United Airlines','UA503','paul@gmail.com',        NULL,'2025-03-03'),
('TKT1015','United Airlines','UA504','emma@gmail.com',       'BA10007','2025-03-04'),
('TKT1016','United Airlines','UA505','liam@gmail.com',        NULL,'2025-03-06'),
('TKT1033','United Airlines','UA501','isabella@gmail.com',   'BA10012','2025-03-08'),

/* ───── Lufthansa ───── */
('TKT1017','Lufthansa','LH602','noah@gmail.com',     'BA10003','2025-03-10'),
('TKT1018','Lufthansa','LH603','ava@gmail.com',              NULL,'2025-03-11'),
('TKT1019','Lufthansa','LH604','isabella@gmail.com', 'BA10008','2025-03-12'),
('TKT1020','Lufthansa','LH605','sophia@gmail.com',           NULL,'2025-03-13'),
('TKT1034','Lufthansa','LH601','paul@gmail.com',     'BA10013','2025-03-14'),

/* ───── Emirates ───── */
('TKT1021','Emirates','EK702','jacob@gmail.com',     'BA10004','2025-03-16'),
('TKT1022','Emirates','EK703','mia@gmail.com',               NULL,'2025-03-17'),
('TKT1023','Emirates','EK704','ethan@gmail.com',     'BA10009','2025-03-18'),
('TKT1024','Emirates','EK705','amelia@gmail.com',            NULL,'2025-03-19'),
('TKT1035','Emirates','EK701','ava@gmail.com',       'BA10014','2025-03-20'),

/* ───── Qatar Airways ───── */
('TKT1025','Qatar Airways','QR802','lucas@gmail.com', 'BA10005','2025-03-22'),
('TKT1026','Qatar Airways','QR803','harper@gmail.com',        NULL,'2025-03-23'),
('TKT1027','Qatar Airways','QR804','logan@gmail.com', 'BA10010','2025-03-24'),
('TKT1028','Qatar Airways','QR805','karen@gmail.com',         NULL,'2025-03-25'),
('TKT1036','Qatar Airways','QR801','emma@gmail.com',  'BA10015','2025-03-26'),

/* ───── British Airways ───── */
('TKT1029','British Airways','BA902','leo@gmail.com',   'BA10006','2025-03-28'),
('TKT1030','British Airways','BA903','maria@gmail.com',         NULL,'2025-03-29'),
('TKT1031','British Airways','BA904','nathan@gmail.com','BA10011','2025-03-30'),
('TKT1032','British Airways','BA905','oliver@gmail.com',        NULL,'2025-03-31'),
('TKT1037','British Airways','BA901','sophia@gmail.com','BA10016','2025-04-01');



UPDATE Customer      SET Password = MD5(Password);
UPDATE Booking_Agent SET Password = MD5(Password);
UPDATE Airline_Staff SET Password = MD5(Password);
