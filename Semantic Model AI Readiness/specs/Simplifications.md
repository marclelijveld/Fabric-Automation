# Simplifications

This markdown file includes suggestions to simplify the existing notebooks. 

## General simplifications
Consider using the TOM Wrapper more in Semantic Link Labs, which has many all functions to list for example: 
- [Columns](https://semantic-link-labs.readthedocs.io/en/latest/sempy_labs.tom.html#sempy_labs.tom.TOMWrapper.all_columns): ```all_columns()```
- [Calculation groups](https://semantic-link-labs.readthedocs.io/en/latest/sempy_labs.tom.html#sempy_labs.tom.TOMWrapper.all_calculated_columns): ```all_calculation_groups()```
- [Measures](https://semantic-link-labs.readthedocs.io/en/latest/sempy_labs.tom.html#sempy_labs.tom.TOMWrapper.all_measures): ```all_measures()```
- [Row level security](https://semantic-link-labs.readthedocs.io/en/latest/sempy_labs.tom.html#sempy_labs.tom.TOMWrapper.all_rls): ```all_rls()``` - note this does not check the roles itself, which could be an OLS role, but not RLS. 


## NB_ANLYZ_02_Model structure & organization
Rule 2, has date table. This can easily be done using the TOM Wrapper in Semantic Link Labs. The function ```has_date_table()``` returns a boolean whether the model contains a date table. 
Combine that with the check that auto-generated date tables should not exist. So point should only be assigned if there is a date table, which is not a auto generated date table. The following function could help here: ```is_auto_date_table()``` 
Each of these functions require a table as input parameter. So a list of available tables in the model should be generated first. 

Docs: https://semantic-link-labs.readthedocs.io/en/latest/sempy_labs.tom.html#sempy_labs.tom.TOMWrapper.has_date_table
docs: https://semantic-link-labs.readthedocs.io/en/latest/sempy_labs.tom.html#sempy_labs.tom.TOMWrapper.has_date_table

