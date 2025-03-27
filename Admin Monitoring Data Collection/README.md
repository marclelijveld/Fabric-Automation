# Save Admin Monitoring data to Lakehouse
This notebook is intended to collect data from the Admin Monitoring workspace and save to a Fabric Lakehouse.

#### Conceptual overview of the solution
As the semantic models in the admin monitoring workspace are in a protected state, you cannot directly connect to the semantic model to collect data. Therefore, an intermediate [composite model](https://learn.microsoft.com/en-us/power-bi/transform-model/desktop-composite-models?WT.mc_id=DP-MVP-5003435) is required. This composite model can be used to directly enrich the data but will not extend the retention. To extract the data and save it to your own lakehouse, you have to run this notebook on top of the composite model. 

In below image you will see an conceptual overview. This notebook is the highlighted notebook. 
<img src="https://private-user-images.githubusercontent.com/38921736/427629709-3a25cb61-1356-480b-927d-e8d38b31c2da.png?jwt=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJnaXRodWIuY29tIiwiYXVkIjoicmF3LmdpdGh1YnVzZXJjb250ZW50LmNvbSIsImtleSI6ImtleTUiLCJleHAiOjE3NDMwODg1MzksIm5iZiI6MTc0MzA4ODIzOSwicGF0aCI6Ii8zODkyMTczNi80Mjc2Mjk3MDktM2EyNWNiNjEtMTM1Ni00ODBiLTkyN2QtZThkMzhiMzFjMmRhLnBuZz9YLUFtei1BbGdvcml0aG09QVdTNC1ITUFDLVNIQTI1NiZYLUFtei1DcmVkZW50aWFsPUFLSUFWQ09EWUxTQTUzUFFLNFpBJTJGMjAyNTAzMjclMkZ1cy1lYXN0LTElMkZzMyUyRmF3czRfcmVxdWVzdCZYLUFtei1EYXRlPTIwMjUwMzI3VDE1MTAzOVomWC1BbXotRXhwaXJlcz0zMDAmWC1BbXotU2lnbmF0dXJlPWRmNjI0MmJmMjg0MjNlMmM0NDhiNWU0ZTI3ZGRiYjhiMjcxNzllODcxNjBiNzIzOGU2NDYyMGMzNWRmOWY4NjkmWC1BbXotU2lnbmVkSGVhZGVycz1ob3N0In0.xDmBDsyqXt7iknmK459C-6l87EMUHQ46F_3JuNtnA7M" width="1000px">

#### <mark>**Risks and caveats:**</mark>

**Solution impact**
- Need to deduplicate dimensional data - as metadata may change over time (or consider slowly changing dimensions instead).
- Semantic model definition may change through updates, which may break your data extraction notebook.
- Impact on capacity through direct query on Admin & Monitoring artifacts

**Permissions & security risks**
- Admin & monitoring artifacts are available to a limited group - for a reason
- Having the data in a lakehouse, makes you responsible to manage retention and security!
