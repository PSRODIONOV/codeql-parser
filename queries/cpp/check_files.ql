import cpp
from File f
where f.getBaseName() = "utils" or f.getBaseName() = "main"
select f.getAbsolutePath() as path, f.getBaseName() as name
