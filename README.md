# Flight System

To render the webapplication on the local pc you need to 
1. Use the applciation manager-OSX
2. Create a Database "flight_ticket_system"
3. Copy and paste the SQL code in the file 'app/SQL/DataBase_SQL.sql' 
4. Make sure that your envirment have the following pakages:
    - Falsk 
    - Matplotlib
    - Numpy 
    - and pip install any other pakages that create import errors 

If the are problem in the connections to the database you can update the default values in "__init__" function in the object "AbstractDatabaseService" in the file "app/Backend/Database_Manager_abstract.py". Any additional problem please email "ap6522@nyu.edu".

