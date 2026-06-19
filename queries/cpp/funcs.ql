import cpp
from Function f
where f.hasDefinition()
select f.getQualifiedName(), f.getFile().getAbsolutePath(), f.getFile().getBaseName()
