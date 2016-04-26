package utils

import Functions.{CocoaLabeledPoint, ProxCocoaDataMatrix, ProxCocoaLabeledPoint}
import breeze.linalg.{DenseVector, SparseVector}
import org.apache.spark.SparkContext
import org.apache.spark.mllib.regression.LabeledPoint
import org.apache.spark.mllib.util.MLUtils
import org.apache.spark.rdd.RDD

import scala.xml.XML

/**
  * Created by amirreza on 12/04/16.
  */
object Utils {
  def loadRawDataset(dataset: String, sc: SparkContext) : RDD[LabeledPoint] = {
    // get projectPath from config
    val xml = XML.loadFile("configs.xml")
    val projectPath = (xml \\ "config" \\ "projectpath") text
    val datasetPath = projectPath + (if (projectPath.endsWith("/")) "" else "/") + "datasets/" + dataset
    //Load data
    val data: RDD[LabeledPoint] = MLUtils.loadLibSVMFile(sc, datasetPath)
    return data
  }

  def loadLibSVMForBinaryClassification(dataset: String, numPartitions: Int = 4, sc: SparkContext):
  (RDD[LabeledPoint],RDD[LabeledPoint]) = {
    val data = loadRawDataset(dataset, sc)
    //Take only two class with labels -1 and +1 for binary classification
    val points = data.filter(p => p.label == 3.0 || p.label == 2.0).
      map(p => if (p.label == 2.0) LabeledPoint(-1.0, p.features)
      else LabeledPoint(+1.0, p.features)).repartition(numPartitions)

    val Array(train, test) = points.randomSplit(Array(0.8, 0.2), seed = 13)
    return (train, test)
  }

  def loadLibSVMForRegression(dataset: String, numPartitions: Int = 4, sc: SparkContext):
  (RDD[LabeledPoint],RDD[LabeledPoint]) = {
    val data = loadRawDataset(dataset, sc)
    val Array(train, test) = data.randomSplit(Array(0.8, 0.2), seed = 13)
    return (train, test)
  }

  def toProxCocoaTranspose(data:RDD[LabeledPoint]): ProxCocoaDataMatrix = {
    val numEx = data.count().toInt
    val myData:RDD[(Double,Array[(Int, (Int, Double))])] = data.zipWithIndex().
      map(p => (p._2, p._1.label, p._1.features.toArray.zipWithIndex)).
      map(x => (x._2, x._3.map(p =>(p._2, (x._1.toInt, p._1)))))

    val y:DenseVector[Double] = new DenseVector[Double](myData.map(x => x._1).collect())
    // arrange RDD by feature
    val feats:RDD[(Int, SparseVector[Double])] = myData.flatMap(x => x._2.iterator)
      .groupByKey().map(x => (x._1, x._2.toArray)).map(x => (x._1, new SparseVector[Double](x._2.map(y => y._1), x._2.map(y => y._2), numEx)))
    return (feats,y)
  }

  def toProxCocoaFormat(data:RDD[LabeledPoint]): ProxCocoaLabeledPoint = {
    data.map(p => l1distopt.utils.LabeledPoint( p.label, SparseVector(p.features.toArray.map(x => x.toDouble))))
  }

  def toCocoaFormat(data:RDD[LabeledPoint]): CocoaLabeledPoint = {
    data.map(p => distopt.utils.LabeledPoint( p.label, SparseVector(p.features.toArray.map(x => x.toDouble))))
  }
}
