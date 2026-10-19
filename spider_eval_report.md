# Spider dev 集评测报告

- 样本数: **99**
- EX (Execution Accuracy): **62.6%** (62/99)
- Executable Rate: **72.7%** (72/99)
- 模型: DeepSeek deepseek-chat
- 耗时: 76s

> 注：数据库由 Spider tables.json schema 重建并填充假数据（保证外键关联）。
> EX = 生成 SQL 与标准答案 SQL 在同一数据库上执行结果集一致（忽略行/列顺序）。

## 失败案例（前 10 条 EX 不通过）

| db_id | question | gold | pred | 原因 |
|-------|----------|------|------|------|
| student_transcripts_tracking | What are the first, middle, and last names, along  | `SELECT T1.first_name ,  T1.middle_name ,  T1.last_name ,  T1` | `SELECT s.student_id, s.first_name, s.middle_name, s.last_nam` | 结果集不一致 |
| pets_1 | What are the ids of the students who do not own ca | `SELECT stuid FROM student EXCEPT SELECT T1.stuid FROM studen` | `SELECT student_id FROM student WHERE student_id NOT IN (SELE` | 结果集不一致 |
| museum_visit | Find the number of visitors who did not visit any  | `SELECT count(*) FROM visitor WHERE id NOT IN (SELECT t2.visi` | `SELECT COUNT(DISTINCT customer_id) FROM visit WHERE museum_i` | 结果集不一致 |
| car_1 | What is the maker of the carr produced in the earl | `SELECT T2.Make ,  T1.Year FROM CARS_DATA AS T1 JOIN CAR_NAME` | `SELECT car_makers.maker, cars_data.year FROM cars_data JOIN ` | 结果集不一致 |
| network_1 | What are the names of high schoolers who have a gr | `SELECT T2.name FROM Friend AS T1 JOIN Highschooler AS T2 ON ` | `SELECT h.name FROM high_schooler h JOIN friend f ON h.id = f` | 结果集不一致 |
| wta_1 | What are the first names of all players, and their | `SELECT avg(ranking) ,  T1.first_name FROM players AS T1 JOIN` | `SELECT players.first_name, AVG(rankings.ranking) FROM player` | 结果集不一致 |
| world_1 | Give the mean life expectancy of countries in whic | `SELECT avg(LifeExpectancy) FROM country WHERE Name NOT IN (S` | `SELECT AVG(country.life_expectancy) FROM country JOIN countr` | 结果集不一致 |
| museum_visit | Find the name and membership level of the visitors | `SELECT name ,  Level_of_membership FROM visitor WHERE Level_` | `SELECT customer.name, customer.level_of_membership FROM cust` | 结果集不一致 |
| network_1 | What are the names of high schoolers who have like | `SELECT T2.name ,  count(*) FROM Likes AS T1 JOIN Highschoole` | `SELECT high_schooler.name, COUNT(likes.liked_id) AS like_cou` | 结果集不一致 |
| wta_1 | How many players are from each country? | `SELECT count(*) ,  country_code FROM players GROUP BY countr` | `SELECT country_code, COUNT(*) FROM players GROUP BY country_` | 结果集不一致 |