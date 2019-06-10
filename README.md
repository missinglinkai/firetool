firetool is a command line tool to perform batch operation on Firebase real time database
It can perform list/copy/delete on the entire database in parallel.   

 - Installing:

       pip install firetool  
       # tested on Python2.7 and Python 3.5
       
For example assume the following db:

     root      
     └─ days      
         ├─ 2017-01-01
         │   ├─ name: foo  
         │   └─ id: 1
         ├─ 2017-01-02
         │   ├─ name: bar
         │   └─ id: 2            
         └─ 2017-01-03
             ├─ name: baz
             └─ id: 3
         
 - Listing:
  
       firetool list --path "days/(.*)/name" --project {project}       
       # This will return the values nodes matching --path 

       firetool list --path "days/(.*)/{name, id}" --project {project}             
       # This will return the values nodes matching --path 

 - Copy:

       firetool copy --src "days/(\d{4})-(\d\d)-(\d\d)" --dest "days/\1/\2/\3"" --project {project}        
       # This will iterate over all the nodes mataching --src (using regex)
       # and will copy the matching nodes into a --dest using regex groups matching
       # The new tree will have those new nodes                                     

       root      
         └─ days      
            └─ 2017
                └─ 01
                    ├─ 01
                    │   ├─ name: foo  
                    │   └─ id: 1
                    ├─ 02                        
                    │   ├─ name: bar
                    │   └─ id: 2            
                    └─ 03
                        ├─ name: baz
                        └─ id: 3

 - Delete:

       firetool delete --path "days/(\d{4})-(\d\d)-(\d\d)" --project {project}       
       # This will delete all the nodes that matches the --path regex
        
 - Remarks        
    - The operations copy and delete has the --dry switch to prevent from the operation to be destructive
    - You need to authenticate using [firebase-tools](https://github.com/firebase/firebase-tools).   
      The same credentials will be used by both tools 
    - firetool is not affiliated with Google
          
