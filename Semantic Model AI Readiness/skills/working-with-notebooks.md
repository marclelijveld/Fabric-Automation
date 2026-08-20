# Working in Fabric Notebooks
This markdown is intended as guidance for developing notebooks. 

## Importing libraries
Keep in mind that some libraries require a <code>% pip install</code> command to be run. This should always be the very first cell and very first line of the notebook after the markdown title and description. 

When using Semantic Link Labs, this does require a pip install command, namely: 
<code>%pip install semantic-link-labs</code>

## Loading libraries
After any potential pip install command, put in the same cell any imports, like the following pieces: 
<code>import sempy.fabric as fabric
import sempy_labs as labs</code>

## Variables
When variables are defined, do that as next step after importing and loading libraries. Make sure the cell defining parameters is also togggled as parameter cell. Documentation describing this feature can be found [here](https://learn.microsoft.com/en-us/fabric/data-engineering/author-execute-notebook#designate-a-parameters-cell). 

