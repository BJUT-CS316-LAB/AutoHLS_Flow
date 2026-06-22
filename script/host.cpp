#include "xcl2.hpp"
#include <cstring>
#include <hls_stream.h>
#include <hls_vector.h>
#include <ap_int.h>
#include "code_generated.h"

typedef hls::vector<float,16> float16;
typedef hls::vector<float,8> float8;
typedef hls::vector<float,4> float4;
typedef hls::vector<float,2> float2;
typedef hls::vector<float,1> float1;

#pragma ACCEL kernel

void kernel_2mm(float alpha,float beta,float tmp[180][190],float A[180][210],float B[210][190],float C[190][220],float D[180][220])
{
  int i;
  int j;
  int k;
{
    for (i = 0; i < 180; i++) {
      for (j = 0; j < 190; j++) {
        tmp[i][j] = 0.0;   
        for (k = 0; k < 210; ++k) {
          tmp[i][j] += alpha * A[i][k] * B[k][j];
        }
      }
    }
    for (i = 0; i < 180; i++) {
      for (j = 0; j < 220; j++) {
        D[i][j] *= beta;
        for (k = 0; k < 190; ++k) {
          D[i][j] += tmp[i][k] * C[k][j];
        }
      }
    }
  }
}

//void kernel_nlp(float alpha, float beta, float2 vtmp[17100], float2 vA[18900], float2 vB[19950], float4 vC[10450], float4 vD[9900]) ;

int main(int argc, char* argv[]){
    for(int i = 0; i < argc; i++){
        std::cout << std::string(argv[i]) << " ";
    }
    std::cout << "\n";
    printf("Starting C-simulation...\n");
    float val;
    float alpha_ori;
    float alpha_new;
    float beta_ori;
    float beta_new;
    float tmp_ori[180][190];
    float tmp_new[180*190];
    float tmp_hold_tmp[180*190];
    float A_ori[180][210];
    float A_new[180*224];
    float B_ori[210][190];
    float B_new[210*192];
    float C_ori[190][220];
    float C_new[190*224];
    float D_ori[180][220];
    float D_new[180*224];
    float D_hold_tmp[180*224];

    val = ((float)rand() / RAND_MAX);
    alpha_ori = val;
    alpha_new = val;
    val = ((float)rand() / RAND_MAX);
    beta_ori = val;
    beta_new = val;
    for(int i0 = 0; i0 < 180; i0++){
        for(int i1 = 0; i1 < 190; i1++){
            val = ((float)rand() / RAND_MAX);
            tmp_ori[i0][i1] = val;
            tmp_hold_tmp[i0*190+i1] = val;
            // tmp_new2
        }
    }
    for(int i0 = 0; i0 < 180; i0++){
        for(int i1 = 0; i1 < 210; i1++){
            val = ((float)rand() / RAND_MAX);
            A_ori[i0][i1] = val;
            A_new[i0*224+i1] = val;
        }
    }


    for(int i0 = 0; i0 < 210; i0++){
        for(int i1 = 0; i1 < 190; i1++){
            val = ((float)rand() / RAND_MAX);
            B_ori[i0][i1] = val;
            B_new[i0*192+i1] = val;
        }
    }

    for(int i0 = 0; i0 < 190; i0++){
        for(int i1 = 0; i1 < 220; i1++){
            val = ((float)rand() / RAND_MAX);
            C_ori[i0][i1] = val;
            C_new[i0*224+i1] = val;
        }
    }

    for(int i0 = 0; i0 < 180; i0++){
        for(int i1 = 0; i1 < 220; i1++){
            val = ((float)rand() / RAND_MAX);
            // val = 0.0;
            D_ori[i0][i1] = val;
            D_hold_tmp[i0*224+i1] = val;
        }
    }

    int memIndex = 0;
    for(int t = 0; t < 20*28; t++){
        int i0_S2_S3 = t/28;
        int j0_S2_S3 = t%28;
        for (int i1 = 0; i1 < 9; i1++) {
            for (int j1 = 0; j1 < 8; j1++) {
                int i = i0_S2_S3 * 9 + i1;
                int j = j0_S2_S3 * 8 + j1;
                D_new[memIndex] = D_hold_tmp[i*224+j];
                memIndex++;
            }
        }
    }

    cl_int err;
	std::vector<cl::Device> devices = xcl::get_xil_devices();
	cl::Device device;

	for(unsigned int i = 0; i < devices.size(); i++){
		device = devices[i];

		std::cout << "Trying to program device[" << i << "]: " << device.getInfo<CL_DEVICE_NAME>() << std::endl;
		#ifndef HW_SIM
		if (device.getInfo<CL_DEVICE_NAME>() == "xilinx_u55c_gen3x16_xdma_base_3") {
		#else
		if (device.getInfo<CL_DEVICE_NAME>() == "xilinx_u55c_gen3x16_xdma_3_202210_1") {
		#endif
			break;
		}
	}

	OCL_CHECK(err, cl::Context context(device, NULL, NULL, NULL, &err));
	OCL_CHECK(err, cl::CommandQueue q(context, device, CL_QUEUE_PROFILING_ENABLE, &err));
	OCL_CHECK(err, std::string device_name = device.getInfo<CL_DEVICE_NAME>(&err));

	//Create Program
    std::string binary(argv[1]);
	auto fileBuf = xcl::read_binary_file(binary);
	cl::Program::Binaries bins{{fileBuf.data(), fileBuf.size()}};

	OCL_CHECK(err, cl::Program program(context, {device}, bins, NULL, &err));
	OCL_CHECK(err, cl::Kernel kernel(program, "kernel_nlp", &err));

    cl::Buffer tmpNewOCL = cl::Buffer(context, CL_MEM_USE_HOST_PTR | CL_MEM_WRITE_ONLY, sizeof(float) * 180 * 190, tmp_hold_tmp, &err);
	if(err != CL_SUCCESS){
		std::cerr << "Could not allocate buffer tmpNewOCL, error number: " << err << "\n";
		return EXIT_FAILURE;
	}
    cl::Buffer ANewOCL = cl::Buffer(context, CL_MEM_USE_HOST_PTR | CL_MEM_READ_ONLY, sizeof(float) * 180 * 224, A_new, &err);
	if(err != CL_SUCCESS){
		std::cerr << "Could not allocate buffer ANewOCL, error number: " << err << "\n";
		return EXIT_FAILURE;
	}
    cl::Buffer BNewOCL = cl::Buffer(context, CL_MEM_USE_HOST_PTR | CL_MEM_READ_ONLY, sizeof(float) * 210 * 192, B_new, &err);
	if(err != CL_SUCCESS){
		std::cerr << "Could not allocate buffer BNewOCL, error number: " << err << "\n";
		return EXIT_FAILURE;
	}
    cl::Buffer CNewOCL = cl::Buffer(context, CL_MEM_USE_HOST_PTR | CL_MEM_READ_ONLY, sizeof(float) * 190 * 224, C_new, &err);
	if(err != CL_SUCCESS){
		std::cerr << "Could not allocate buffer CNewOCL, error number: " << err << "\n";
		return EXIT_FAILURE;
	}
    cl::Buffer DNewOCL = cl::Buffer(context, CL_MEM_USE_HOST_PTR | CL_MEM_READ_WRITE, sizeof(float) * 180 * 224, D_new, &err);
	if(err != CL_SUCCESS){
		std::cerr << "Could not allocate buffer DNewOCL, error number: " << err << "\n";
		return EXIT_FAILURE;
	}

    int argN = 0;
    kernel.setArg(argN++, alpha_new);
    kernel.setArg(argN++, beta_new);
    kernel.setArg(argN++, tmpNewOCL);
    kernel.setArg(argN++, ANewOCL);
    kernel.setArg(argN++, BNewOCL);
    kernel.setArg(argN++, CNewOCL);
    kernel.setArg(argN++, DNewOCL);

    OCL_CHECK(err, err = q.enqueueMigrateMemObjects({ANewOCL, BNewOCL, CNewOCL, DNewOCL}, 0, nullptr, nullptr));
	q.finish();

    cl::Event kernelCompute;
    OCL_CHECK(err, err = q.enqueueTask(kernel, nullptr, &kernelCompute));
	q.finish();
    kernelCompute.wait();

    OCL_CHECK(err, err = q.enqueueMigrateMemObjects({tmpNewOCL, DNewOCL}, CL_MIGRATE_MEM_OBJECT_HOST, nullptr, nullptr));
	q.finish();

    kernel_2mm(alpha_ori, beta_ori, tmp_ori, A_ori, B_ori, C_ori, D_ori);
    //kernel_nlp(alpha_new, beta_new, (float2 *)  tmp_new, (float2 *) A_new, (float2 *) B_new, (float4 *) C_new, (float4 *) D_new);
    if(abs(alpha_ori - alpha_new) > 0.01){
        printf("Error in alpha...\n");
        return 1;
    }
    if(abs(beta_ori - beta_new) > 0.01){
        printf("Error in beta...\n");
        return 1;
    }

    memIndex = 0;
    for(int t = 0; t < 20*19; t++){
        int i0_S1_S2 = t / 19;
        int j0_S1_S2 = t % 19;
        //if (i0_S1_S2 < 20 && j0_S1_S2 < 19){
        for (int i1 = 0; i1 < 9; i1++) {
            for (int j1 = 0; j1 < 10; j1++) {
                int i = i0_S1_S2 * 9 + i1;
                int j = j0_S1_S2 * 10 + j1;

                tmp_new[i*190+j] = tmp_hold_tmp[memIndex];
                memIndex++;
            }
        //}
        }
    }

    int id_ = 0; 
    for(int i0 = 0; i0 < 180; i0++){
        for(int i1 = 0; i1 < 190; i1++){
            if(abs(tmp_ori[i0][i1] - tmp_new[i0*190+i1]) > 0.01){
                printf("Error in tmp... %d %d %f %f\n", i0, i1, tmp_ori[i0][i1], tmp_new[i0*190+i1]);
                return 1;
            }
        }
    }
    printf("tmp passed!\n");

    memIndex = 0;
    for(int t = 0; t < 20*28; t++){
        int i0_S2_S3 = t/28;
        int j0_S2_S3 = t%28;

        for(int i1 = 0; i1 < 9; i1++) {
            for(int j1 = 0; j1 < 8; j1++) {
                int i = i0_S2_S3 * 9 + i1;
                int j = j0_S2_S3 * 8 + j1;
                D_hold_tmp[i*224+j] = D_new[memIndex];
                memIndex++;
            }
        }
    }
    
    id_ = 0; 
    for(int i0 = 0; i0 < 180; i0++){
        for(int i1 = 0; i1 < 220; i1++){
            if (id_ == 0){
                printf("Good in D[%d][%d] = %f, %f\n", i0, i1, D_ori[i0][i1], D_hold_tmp[i0*224+i1]);
                id_++;
            }
            if(abs(D_ori[i0][i1] - D_hold_tmp[i0*224+i1]) > 0.01){
                printf("Error in D[%d][%d] = %f, %f\n", i0, i1, D_ori[i0][i1], D_hold_tmp[i0*224+i1]);
                // printf("Error in D[%d][%d] = %f, %f\n", i0, i1, D_ori[i0][i1], D_hold_tmp[i0][i1]);

                return 1;
            }
        }
    }
    printf("C-simulation passed!\n");
    uint64_t executionTime = kernelCompute.getProfilingInfo<CL_PROFILING_COMMAND_END>() - kernelCompute.getProfilingInfo<CL_PROFILING_COMMAND_START>();
    std::cout << "Time in seconds: " << (double)executionTime/pow(1000,3) << "\n";
    
    return 0;
}
