# Save Admin Monitoring data to Lakehouse
This notebook is intended to collect data from the Admin Monitoring workspace and save to a Fabric Lakehouse.

#### Conceptual overview of the solution
As the semantic models in the admin monitoring workspace are in a protected state, you cannot directly connect to the semantic model to collect data. Therefore, an intermediate [composite model](https://learn.microsoft.com/en-us/power-bi/transform-model/desktop-composite-models?WT.mc_id=DP-MVP-5003435) is required. This composite model can be used to directly enrich the data but will not extend the retention. To extract the data and save it to your own lakehouse, you have to run this notebook on top of the composite model. 

In below image you will see an conceptual overview. This notebook is the highlighted notebook. 
<img src="https://dataandai.wordpress.com/wp-content/uploads/2025/04/adminmonitoringworkspacedatacollection-conceptualoverview.png" width="1000px">

#### <mark>**Risks and caveats:**</mark>

**Solution impact**
- Need to deduplicate dimensional data - as metadata may change over time (or consider slowly changing dimensions instead). This notebook does not deduplicate the data in the destination lakehouse. 
- Semantic model definition of the Admin Monitoring Semantic Model may change through updates, which may break this data extraction notebook.
- Impact on capacity through direct query on Admin & Monitoring artifacts. 

**Permissions & security risks**
- Admin & monitoring artifacts are available to a limited group - for a reason.
- Having the data in a lakehouse, makes you responsible to manage retention and security!
