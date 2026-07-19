-- MySQL dump 10.13  Distrib 8.4.9, for Linux (x86_64)
--
-- Host: localhost    Database: smart_pantry
-- ------------------------------------------------------
-- Server version	8.4.9-0ubuntu0.26.04.1

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!50503 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;

--
-- Table structure for table `prodotti`
--

DROP TABLE IF EXISTS `prodotti`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `prodotti` (
  `id` int NOT NULL AUTO_INCREMENT,
  `nome` varchar(50) NOT NULL,
  `categoria` varchar(50) DEFAULT NULL,
  `allergene` varchar(100) DEFAULT NULL,
  `alcolico` tinyint(1) DEFAULT '0',
  `alternativa` varchar(100) DEFAULT NULL,
  `alternativa2` varchar(100) DEFAULT NULL,
  `alternativa3` varchar(100) DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=29 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `prodotti`
--

LOCK TABLES `prodotti` WRITE;
/*!40000 ALTER TABLE `prodotti` DISABLE KEYS */;
INSERT INTO `prodotti` VALUES (1,'mela','frutta',NULL,0,'banana',NULL,NULL),(3,'pane','alimento','glutine',0,'pane senza glutine',NULL,NULL),(5,'cracker','snack','glutine',0,'cracker senza glutine',NULL,NULL),(6,'latte','bevanda','lattosio',0,'latte senza lattosio',NULL,NULL),(7,'yogurt','latticino','lattosio',0,'yogurt senza lattosio',NULL,NULL),(8,'uova','alimento','uova',0,'tofu',NULL,NULL),(9,'birra','bevanda',NULL,1,'acqua',NULL,NULL),(10,'vino','bevanda',NULL,1,'succo di frutta',NULL,NULL),(19,'banana','frutta',NULL,0,'mela','pera','arancia'),(20,'apple','frutta',NULL,0,'banana','pera','kiwi'),(21,'orange','frutta',NULL,0,'mela','banana','mandarino'),(22,'broccoli','verdura',NULL,0,'zucchine','spinaci','cavolfiore'),(23,'carrot','verdura',NULL,0,'zucchine','finocchi','broccoli'),(24,'pizza','panificato','glutine, lattosio',0,'pizza senza glutine con mozzarella senza lattosio','piadina di mais con verdure','base di riso o mais con pomodoro e verdure'),(25,'sandwich','panificato','glutine, lattosio, uova',0,'sandwich con pane senza glutine','wrap di mais con verdure','panino senza glutine senza salse con uova o latte'),(26,'hot dog','panificato','glutine, lattosio, senape',0,'hot dog con pane senza glutine','panino con pollo o tacchino','panino con verdure grigliate'),(27,'donut','dolce','glutine, lattosio, uova',0,'dolce senza glutine e senza lattosio','muffin vegano senza latte e senza uova','frutta fresca o barretta di riso soffiato'),(28,'cake','dolce','glutine, lattosio, uova, frutta a guscio',0,'torta senza glutine e senza lattosio','torta vegana senza latte e senza uova','frutta fresca con yogurt senza lattosio');
/*!40000 ALTER TABLE `prodotti` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `utenti`
--

DROP TABLE IF EXISTS `utenti`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `utenti` (
  `id` int NOT NULL AUTO_INCREMENT,
  `nome` varchar(50) NOT NULL,
  `eta` int NOT NULL,
  `allergia` varchar(100) DEFAULT NULL,
  `intolleranza` varchar(100) DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=4 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `utenti`
--

LOCK TABLES `utenti` WRITE;
/*!40000 ALTER TABLE `utenti` DISABLE KEYS */;
INSERT INTO `utenti` VALUES (1,'Pasquale',17,NULL,NULL),(2,'Carmine',21,'uova','lattosio'),(3,'Francesco',23,'glutine',NULL);
/*!40000 ALTER TABLE `utenti` ENABLE KEYS */;
UNLOCK TABLES;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

-- Dump completed on 2026-06-17  7:58:20
