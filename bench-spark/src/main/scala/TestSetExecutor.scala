// this script is currently only meant for demonstration purposes

import org.rogach.scallop._

class CLI(arguments: Seq[String]) extends org.rogach.scallop.ScallopConf(arguments) {
}

object TestSetExecutor {
  // system specific parameters
  val fileSystem = Array("/scratch/user/", "/tmpfs")
  val inputSizeInGB = Array(8, 16, 32, 64, 128)
  val numOfNodes = Array(4, 8, 16, 32)

  // spark specific parameters
  // here the parameters should also be definable in combination: execPerNode:4 AND ramPerExec:16
  val coresPerExecutor = Array(4, 8, 12)
  val ramPerExecutor = Array(16, 8, 6)

  // alg specific parameters
  val jar  = "/path/to/target/scala-2.10/bench_2.10-0.1.jar"
  val algorithms = Array("L1_Lasso_GD", "L2_SVM_SGD")
  val linRegIterations = Array(1, 10, 20)
  val linRegBatchSize = Array(0.1, 0.2, 0.3)

  def main(angs: Array[String]) {
    for (fs <- fileSystem) {
      for (inSize <- inputSizeInGB) {
        for (nnodes <- numOfNodes) {
          for (cpe <- coresPerExecutor) {
            for (alg <- algorithms) {
              for (rpe <- ramPerExecutor) {
                for (lri <- linRegIterations) {
                  for (lrb <- linRegBatchSize) {
                    // prepare

                    // run
                    val sparkSpec = "spark-submit --executor-cores " + cpe + " --executor-memory " + rpe
                    val algSpec = " --class " + alg + " " + jar + " --iterations " + lri + " --batch-size " + lrb
                    val cmd = sparkSpec + algSpec
                    print("Run somehow this command (running the command is different on HPC infrastructure and AWS -> abstraction required.\n")
                    print(cmd + "\n")

                    // evaluate
                  }
                }
              }
            }
          }
        }
      }
    }
  }
}
